# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Nothing may COMMIT inside a savepoint region.

A COMMIT ends the transaction and takes every savepoint with it, so the
``RELEASE SAVEPOINT`` / ``ROLLBACK TO SAVEPOINT`` that follows fails with MariaDB error
1305. In :meth:`eInvoice.fetch_content_from_platform` the RELEASE sits in an ``else``
clause, so that error escaped the very handler meant to record the failure: the invoice
stayed at ``pending`` with no error text, forever, and the hourly retry reproduced it
exactly. Incoming SuperPDP invoices arrived as empty records because of it.

The tests below cannot simply perform a real COMMIT — the suite isolates each case with a
rollback, and one real commit would poison the run. They model MariaDB's semantics
instead: commit is intercepted, and a savepoint that a commit has invalidated raises the
way the database would.
"""

import os
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests.utils import toggle_test_mode

from etransactions.components.superpdp.models import IncomingFlow
from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice
from etransactions.tests.test_incoming_flow import GET_CLIENT, _FakePlatformClient
from etransactions.tests.utils import eTransactionsTestSuite


class SavepointDestroyedError(Exception):
	"""What MariaDB raises as error 1305 when the savepoint is gone."""


@contextmanager
def modelled_transaction():
	"""Model the database's savepoint lifetime without committing anything.

	Records every commit that happens while a savepoint is live — that is the defect —
	and makes a later use of an invalidated savepoint fail the way the real database
	would, so the consequence is visible in the test rather than only in production.

	Test mode is switched off for the duration, because the commits that caused this
	were guarded by ``if not frappe.flags.in_test`` and so never ran under test — which
	is precisely why the suite could not see the bug. Nothing reaches the database:
	``commit`` is intercepted and does not delegate.
	"""
	live: set[str] = set()
	violations: list[str] = []
	real_savepoint = frappe.db.savepoint
	real_release = frappe.db.release_savepoint
	real_rollback = frappe.db.rollback

	def savepoint(save_point):
		live.add(save_point)
		return real_savepoint(save_point)

	def commit(*args, **kwargs):
		violations.extend(sorted(live))
		live.clear()

	def release_savepoint(save_point):
		if save_point not in live:
			raise SavepointDestroyedError(f"SAVEPOINT {save_point} does not exist")
		live.discard(save_point)
		return real_release(save_point)

	def rollback(*args, save_point=None, **kwargs):
		if save_point is not None:
			if save_point not in live:
				raise SavepointDestroyedError(f"SAVEPOINT {save_point} does not exist")
			live.discard(save_point)
			return real_rollback(save_point=save_point)
		live.clear()
		return real_rollback(**kwargs)

	report = frappe._dict(violations=violations)
	toggle_test_mode(False)
	try:
		with (
			patch.object(frappe.db, "savepoint", savepoint),
			patch.object(frappe.db, "commit", commit),
			patch.object(frappe.db, "release_savepoint", release_savepoint),
			patch.object(frappe.db, "rollback", rollback),
		):
			yield report
	finally:
		toggle_test_mode(True)


class TestContentFetchTransactionSafety(eTransactionsTestSuite):
	def setUp(self):
		super().setUp()
		frappe.db.set_default("company", "_Test Company")

	def _flow(self, flow_id) -> IncomingFlow:
		return IncomingFlow(
			flow_id=flow_id,
			submitted_at="2026-06-01 00:00:00",
			updated_at=None,
			flow_type="SupplierInvoice",
			syntax=None,
		)

	def _incoming(self, flow_id):
		return eInvoice.create_from_plateforme_flow(self._flow(flow_id), None, "_Test Company")

	def _fixture(self, folder, file_name) -> bytes:
		# get_app_path scrubs its arguments, so the file name is joined separately
		folder_path = frappe.get_app_path("etransactions", "tests", "invoices", folder)
		with open(os.path.join(folder_path, file_name), "rb") as f:
			return f.read()

	def _facturx_pdf(self) -> bytes:
		return self._fixture(
			"1.basic_wl", "Facture_F20220023-LE_FOURNISSEUR-POUR-LE_CLIENT_BASIC_WL.pdf"
		)

	def _ubl_xml(self) -> bytes:
		return self._fixture("5.ubl", "UBL-Invoice-2.1-Example.xml")

	def test_a_successful_fetch_takes_no_commit_while_its_savepoint_is_open(self):
		einvoice = self._incoming("FLOW-TXN-001")
		client = _FakePlatformClient(content=self._facturx_pdf())

		with modelled_transaction() as txn, patch(GET_CLIENT, return_value=client):
			einvoice.fetch_content_from_platform()

		self.assertEqual(txn.violations, [], "a commit inside the region destroys the savepoint")
		einvoice.reload()
		self.assertEqual(einvoice.pa_content_state, "fetched")

	def test_a_readable_pdf_fetch_takes_no_commit_either(self):
		"""The readable-PDF call logs three more times, from inside the same region."""
		einvoice = self._incoming("FLOW-TXN-002")
		client = _FakePlatformClient(content=self._ubl_xml(), readable_pdf=self._facturx_pdf())

		with modelled_transaction() as txn, patch(GET_CLIENT, return_value=client):
			einvoice.fetch_content_from_platform()

		self.assertEqual(txn.violations, [])

	def test_a_failed_download_still_reaches_its_error_handler(self):
		einvoice = self._incoming("FLOW-TXN-003")
		client = _FakePlatformClient(error=Exception("platform unavailable"))

		with modelled_transaction() as txn, patch(GET_CLIENT, return_value=client):
			einvoice.fetch_content_from_platform()

		self.assertEqual(txn.violations, [])
		einvoice.reload()
		self.assertEqual(einvoice.pa_content_state, "error")
		self.assertIn("platform unavailable", einvoice.pa_content_error)

	def test_a_failed_parse_still_reaches_its_error_handler(self):
		"""The case the user hit: the download succeeded and the parse did not."""
		einvoice = self._incoming("FLOW-TXN-004")
		client = _FakePlatformClient(content=self._facturx_pdf())

		with (
			modelled_transaction() as txn,
			patch(GET_CLIENT, return_value=client),
			patch.object(eInvoice, "save", side_effect=Exception("parser choked")),
		):
			einvoice.fetch_content_from_platform()

		self.assertEqual(txn.violations, [])
		einvoice.reload()
		self.assertEqual(einvoice.pa_content_state, "error")
		self.assertIn("parser choked", einvoice.pa_content_error)

	def test_the_audit_trail_of_a_call_that_reached_the_platform_outlives_a_failed_parse(self):
		"""The reason log_fetch used to commit — met without committing."""
		einvoice = self._incoming("FLOW-TXN-005")
		client = _FakePlatformClient(content=self._facturx_pdf())

		with (
			patch(GET_CLIENT, return_value=client),
			patch.object(eInvoice, "save", side_effect=Exception("parser choked")),
		):
			einvoice.fetch_content_from_platform()

		self.assertTrue(
			frappe.db.exists(
				"eInvoice Log",
				{"einvoice": einvoice.name, "operation": "download_flow", "status": "success"},
			),
			"the record of the download must survive the rollback of the parse",
		)

	def test_the_flow_poller_takes_no_commit_inside_its_per_flow_savepoint(self):
		from etransactions.plateforme_agreee.flow import _ingest_incoming_flow

		flow = self._flow("FLOW-TXN-006")

		with modelled_transaction() as txn:
			frappe.db.savepoint("einvoice_flow_0")
			with patch("frappe.enqueue"):
				_ingest_incoming_flow(flow, "_Test Company")
			frappe.db.release_savepoint("einvoice_flow_0")

		self.assertEqual(txn.violations, [])
