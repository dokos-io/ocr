# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from etransactions.overrides.sales_invoice import _transmitted_einvoice, before_cancel


def _row(pa_flow_id="FLOW-1", pa_status="sent"):
	return frappe._dict(name="EINV-1", pa_flow_id=pa_flow_id, pa_status=pa_status)


class TestCancelGuard(UnitTestCase):
	"""Cancelling a Sales Invoice already transmitted to the PA must be blocked
	unless the guided flow (which reports the 'Cancelled' status) confirmed it."""

	def setUp(self):
		frappe.flags.etransactions_cancel_confirmed = False

	def tearDown(self):
		frappe.flags.etransactions_cancel_confirmed = False

	def _before_cancel(self, row):
		doc = SimpleNamespace(name="SINV-TEST")
		with patch(
			"etransactions.overrides.sales_invoice.frappe.db.get_value", return_value=row
		):
			before_cancel(doc, None)

	def test_blocks_transmitted_invoice(self):
		with self.assertRaises(frappe.ValidationError):
			self._before_cancel(_row())

	def test_allows_untransmitted_invoice(self):
		self._before_cancel(None)
		self._before_cancel(_row(pa_flow_id=None))

	def test_allows_errored_or_rejected_flows(self):
		# Errored/rejected flows never reached the buyer: no lifecycle status needed.
		self._before_cancel(_row(pa_status="error"))
		self._before_cancel(_row(pa_status="rejected"))

	def test_confirmed_flag_bypasses_guard(self):
		frappe.flags.etransactions_cancel_confirmed = True
		self._before_cancel(_row())

	def test_transmitted_einvoice_filters(self):
		with patch(
			"etransactions.overrides.sales_invoice.frappe.db.get_value",
			return_value=_row(pa_status="approved"),
		):
			self.assertIsNotNone(_transmitted_einvoice("SINV-TEST"))
		with patch(
			"etransactions.overrides.sales_invoice.frappe.db.get_value",
			return_value=_row(pa_status="error"),
		):
			self.assertIsNone(_transmitted_einvoice("SINV-TEST"))


class TestCancelWithLifecycle(UnitTestCase):
	"""The guided endpoint reports 'cancelled' where the platform can carry it,
	skips with a note where it can't, and always cancels the document."""

	def _run(self, platform_supports: bool):
		invoice = SimpleNamespace(company="_Test Company", cancelled=False)
		invoice.check_permission = lambda perm: None
		invoice.cancel = lambda: setattr(invoice, "cancelled", True)

		einvoice = SimpleNamespace(statuses=[])
		einvoice.submit_lifecycle_status = lambda status: einvoice.statuses.append(status)

		def get_doc(doctype, name):
			return {"Sales Invoice": invoice, "eInvoice": einvoice}[doctype]

		from etransactions.overrides.sales_invoice import cancel_with_lifecycle

		with (
			patch("etransactions.overrides.sales_invoice.frappe.get_doc", side_effect=get_doc),
			patch(
				"etransactions.overrides.sales_invoice.frappe.db.get_value",
				return_value=_row(),
			),
			patch(
				"etransactions.plateforme_agreee.auto_status._platform_supports",
				return_value=platform_supports,
			),
			patch("etransactions.overrides.sales_invoice.frappe.msgprint") as msgprint,
		):
			cancel_with_lifecycle("SINV-TEST")
		return invoice, einvoice, msgprint

	def test_cdar_platform_sends_cancelled_then_cancels(self):
		invoice, einvoice, _ = self._run(platform_supports=True)
		self.assertEqual(einvoice.statuses, ["cancelled"])
		self.assertTrue(invoice.cancelled)
		self.assertFalse(frappe.flags.etransactions_cancel_confirmed)

	def test_unsupported_platform_skips_status_with_note_and_cancels(self):
		invoice, einvoice, msgprint = self._run(platform_supports=False)
		self.assertEqual(einvoice.statuses, [])
		self.assertTrue(invoice.cancelled)
		msgprint.assert_called_once()
