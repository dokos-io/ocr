# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Automatic lifecycle statuses driven by ordinary accounting actions.

An accounting action must never push a status that contradicts what has already been
reported: submitting a Purchase Invoice for an e-invoice the user refused must not report
'Approved'. Skipping is the expected outcome, not a failure, so it is recorded as a
comment on the eInvoice instead of an error in the log.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from etransactions.components.superpdp.models import IncomingFlow
from etransactions.etransactions.doctype.einvoice.einvoice import (
	eInvoice,
	get_transaction_einvoice,
)
from etransactions.etransactions.doctype.einvoice_event.einvoice_event import record_event
from etransactions.plateforme_agreee.auto_status import (
	einvoice_for_purchase_invoice,
	run_auto_lifecycle_status,
)
from etransactions.tests.utils import eTransactionsTestSuite

GET_CLIENT = "etransactions.plateforme_agreee.session.get_client"
# auto_status imports this name at module level, so it has to be patched there.
GET_PLATFORM = "etransactions.plateforme_agreee.auto_status.get_platform_for_company"


class _FakeClient:
	"""Records what it was asked to send instead of calling a platform."""

	def __init__(self):
		self.sent = []

	def submit_lifecycle_status(self, flow_id, status, einvoice=None, details=None):
		self.sent.append((status, details))
		return SimpleNamespace(state="sent", event_id=f"EV-{len(self.sent)}", flow_id=flow_id)


class TestAutomaticLifecycleStatus(eTransactionsTestSuite):
	def setUp(self):
		super().setUp()
		frappe.db.set_default("company", "_Test Company")

	def _einvoice(self, flow_id):
		return eInvoice.create_from_plateforme_flow(
			IncomingFlow(
				flow_id=flow_id,
				submitted_at="2026-06-01 00:00:00",
				updated_at=None,
				flow_type="SupplierInvoice",
				syntax=None,
			),
			None,
			"_Test Company",
		)

	def _run(self, einvoice, status, platform_type="Esalink", client=None, **kwargs):
		"""Run the background auto-send with a stubbed platform. Returns the fake client.

		Pass ``client`` to keep the same stub across several sends: a real platform hands
		out a distinct event id every time, and record_event dedups on it.
		"""
		client = client or _FakeClient()
		platform = SimpleNamespace(platform_type=platform_type) if platform_type else None
		with (
			patch(GET_PLATFORM, return_value=platform),
			patch(GET_CLIENT, return_value=client),
		):
			run_auto_lifecycle_status(einvoice.name, status, "purchases", **kwargs)
		return client

	def _comments(self, einvoice):
		return frappe.get_all(
			"Comment",
			filters={
				"reference_doctype": "eInvoice",
				"reference_name": einvoice.name,
				"comment_type": "Comment",
			},
			pluck="content",
		)

	# ------------------------------------------------------------------
	# The reported scenario
	# ------------------------------------------------------------------
	def test_a_refused_invoice_does_not_get_an_automatic_approval(self):
		einvoice = self._einvoice("FLOW-AUTO-001")
		record_event(
			einvoice.name, direction="out", status="refused", status_datetime="2026-06-02 10:00:00"
		)

		client = self._run(einvoice, "approved")

		self.assertEqual(client.sent, [], "'Approved' must not reach the platform after a refusal")
		self.assertEqual(
			frappe.db.count("eInvoice Event", {"einvoice": einvoice.name, "status": "approved"}), 0
		)

	def test_a_skipped_auto_send_is_explained_not_logged_as_an_error(self):
		einvoice = self._einvoice("FLOW-AUTO-002")
		record_event(
			einvoice.name, direction="out", status="refused", status_datetime="2026-06-02 10:00:00"
		)

		with patch("frappe.log_error") as log_error:
			self._run(einvoice, "approved")

		log_error.assert_not_called()
		comments = self._comments(einvoice)
		self.assertTrue(comments, "the skip should leave an audit trail on the eInvoice")
		self.assertIn("Approved", comments[0])

	def test_a_status_already_reported_is_not_sent_again(self):
		einvoice = self._einvoice("FLOW-AUTO-003")
		record_event(
			einvoice.name, direction="out", status="in_hand", status_datetime="2026-06-02 10:00:00"
		)

		client = self._run(einvoice, "in_hand")

		self.assertEqual(client.sent, [])
		self.assertEqual(
			frappe.db.count("eInvoice Event", {"einvoice": einvoice.name, "status": "in_hand"}),
			1,
			"the timeline must not repeat the same status",
		)

	# ------------------------------------------------------------------
	# What must keep working
	# ------------------------------------------------------------------
	def test_an_allowed_status_still_reaches_the_platform(self):
		einvoice = self._einvoice("FLOW-AUTO-004")
		record_event(
			einvoice.name, direction="out", status="in_hand", status_datetime="2026-06-02 10:00:00"
		)

		client = self._run(einvoice, "approved")

		self.assertEqual([status for status, _details in client.sent], ["approved"])
		self.assertTrue(
			frappe.db.exists("eInvoice Event", {"einvoice": einvoice.name, "status": "approved"})
		)

	def test_successive_payments_are_both_reported(self):
		# Two Payment Entries against one invoice legitimately report 'Payment Sent'
		# twice, with different amounts — blocking the repeat would lose an event.
		einvoice = self._einvoice("FLOW-AUTO-005")
		client = _FakeClient()
		self._run(einvoice, "payment_sent", client=client, amount=40.0, payment_date="2026-06-03")
		self._run(einvoice, "payment_sent", client=client, amount=60.0, payment_date="2026-06-04")

		self.assertEqual([status for status, _details in client.sent], ["payment_sent"] * 2)
		self.assertEqual(
			frappe.db.count("eInvoice Event", {"einvoice": einvoice.name, "status": "payment_sent"}),
			2,
		)

	def test_an_unsupported_status_short_circuits_before_the_guard(self):
		# The platform capability check must stay first: a status SuperPDP cannot carry
		# is not a state-machine problem and should not be reported as one.
		einvoice = self._einvoice("FLOW-AUTO-006")

		client = self._run(einvoice, "suspended", platform_type="SuperPDP")

		self.assertEqual(client.sent, [])
		self.assertEqual(self._comments(einvoice), [])

	def test_an_automatic_send_is_logged_as_automatic(self):
		einvoice = self._einvoice("FLOW-AUTO-007")

		self._run(einvoice, "in_hand")

		self.assertTrue(
			frappe.db.exists(
				"eInvoicing Log", {"operation_type": "lifecycle_send", "origin": "Automatic"}
			),
			"an auto-send used to be recorded as a manual one",
		)


class TestPurchaseInvoiceResolution(eTransactionsTestSuite):
	"""Resolving the eInvoice behind a Purchase Invoice.

	Regression guard: this used to filter Supplier Invoice on `original_invoice`, a field
	removed from the doctype, so the lookup raised on every Purchase Invoice refresh.
	"""

	def test_the_chain_goes_through_supplier_invoice(self):
		looked_up = []

		def router(doctype, name, fieldname=None, *args, **kwargs):
			looked_up.append((doctype, fieldname))
			return {
				"Purchase Invoice": "SINV-1",
				"Supplier Invoice": "EINV-1",
				"eInvoice": "FLOW-1",
			}.get(doctype)

		with patch("frappe.db.get_value", side_effect=router):
			self.assertEqual(einvoice_for_purchase_invoice("PINV-1"), "EINV-1")

		self.assertIn(("Purchase Invoice", "supplier_invoice"), looked_up)
		self.assertIn(("Supplier Invoice", "einvoice"), looked_up)

	def test_an_invoice_without_an_einvoice_resolves_to_nothing(self):
		# Runs the real SQL: a query against a column that no longer exists would raise
		# here even though nothing matches.
		self.assertIsNone(einvoice_for_purchase_invoice("PINV-DOES-NOT-EXIST"))

	def test_the_transaction_lookup_does_not_raise(self):
		doc = SimpleNamespace(check_permission=lambda perm: None)
		with patch("frappe.get_doc", return_value=doc):
			self.assertIsNone(get_transaction_einvoice("Purchase Invoice", "PINV-DOES-NOT-EXIST"))
