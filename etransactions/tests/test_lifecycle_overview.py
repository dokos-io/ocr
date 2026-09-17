# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""The platform status overview shown on a received invoice.

What matters is precedence — the headline must show what needs attention first — and
that the steps and history tell the same story as the recorded events.
"""

from unittest.mock import patch

import frappe

from etransactions.components.superpdp.models import IncomingFlow
from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice
from etransactions.etransactions.doctype.einvoice_event.einvoice_event import record_event
from etransactions.plateforme_agreee import lifecycle_overview
from etransactions.tests.utils import eTransactionsTestSuite


class TestLifecycleOverview(eTransactionsTestSuite):
	def setUp(self):
		super().setUp()
		frappe.db.set_default("company", "_Test Company")

	def _einvoice(self, flow_id, content_state="fetched"):
		doc = eInvoice.create_from_plateforme_flow(
			IncomingFlow(
				flow_id=flow_id,
				submitted_at="2026-06-01 09:00:00",
				updated_at=None,
				flow_type="SupplierInvoice",
				syntax=None,
			),
			None,
			"_Test Company",
		)
		doc.db_set("pa_content_state", content_state, update_modified=False)
		return doc

	def _event(self, einvoice, status, when, direction="out", **kwargs):
		return record_event(einvoice.name, direction=direction, status=status, status_datetime=when, **kwargs)

	def _overview(self, einvoice):
		return lifecycle_overview.get_overview(einvoice.name)

	def _steps(self, overview):
		return [(s["key"], s["state"]) for s in overview["steps"]]

	# ------------------------------------------------------------------
	# Headline precedence
	# ------------------------------------------------------------------
	def test_a_fresh_flow_is_received_and_waits_for_in_hand(self):
		overview = self._overview(self._einvoice("FLOW-OV-001"))

		self.assertEqual(overview["key"], "received")
		self.assertEqual(
			self._steps(overview),
			[("received", "done"), ("in_hand", "current"), ("decision", "todo"), ("payment", "todo")],
		)

	def test_in_hand_awaits_the_buyers_decision(self):
		einvoice = self._einvoice("FLOW-OV-002")
		self._event(einvoice, "in_hand", "2026-06-02 10:00:00", state="done")

		overview = self._overview(einvoice)

		self.assertEqual(overview["key"], "in_hand")
		self.assertEqual(overview["tone"], "blue")
		self.assertEqual(self._steps(overview)[2], ("decision", "current"))
		self.assertIn("approved", {a["status"] for a in overview["actions"]})

	def test_a_dispute_shows_its_reason_on_the_decision_step(self):
		einvoice = self._einvoice("FLOW-OV-003")
		self._event(einvoice, "in_hand", "2026-06-02 10:00:00", state="done")
		self._event(einvoice, "dispute", "2026-06-03 10:00:00", state="done", reason_code="QTE_ERR")

		overview = self._overview(einvoice)
		decision = overview["steps"][2]

		self.assertEqual(overview["key"], "dispute")
		self.assertEqual(overview["tone"], "orange")
		self.assertEqual(decision["state"], "warning")
		self.assertEqual(decision["note"], "Incorrect quantity")

	def test_approved_waits_for_payment_then_paid_completes(self):
		einvoice = self._einvoice("FLOW-OV-004")
		self._event(einvoice, "approved", "2026-06-03 10:00:00", state="done")

		overview = self._overview(einvoice)
		self.assertEqual(overview["key"], "approved")
		# 'In hand' was never reported, but a decision implies it.
		self.assertEqual(
			self._steps(overview),
			[("received", "done"), ("in_hand", "done"), ("decision", "done"), ("payment", "current")],
		)

		self._event(einvoice, "payment_sent", "2026-06-10 10:00:00", state="done")
		overview = self._overview(einvoice)
		self.assertEqual(overview["key"], "payment_sent")
		self.assertEqual(self._steps(overview)[3], ("payment", "done"))

	def test_a_refusal_is_final_and_payment_does_not_apply(self):
		einvoice = self._einvoice("FLOW-OV-005")
		self._event(einvoice, "refused", "2026-06-03 10:00:00", state="done", reason_code="DOUBLON")

		overview = self._overview(einvoice)

		self.assertEqual(overview["key"], "refused")
		self.assertEqual(self._steps(overview)[2:], [("decision", "error"), ("payment", "skipped")])
		self.assertNotIn("approved", {a["status"] for a in overview["actions"]})

	def test_cancellation_wins_over_the_purchase_axis(self):
		einvoice = self._einvoice("FLOW-OV-006")
		self._event(einvoice, "approved", "2026-06-03 10:00:00", state="done")
		self._event(einvoice, "cancelled", "2026-06-04 10:00:00", direction="in", state="done")

		overview = self._overview(einvoice)

		self.assertEqual(overview["key"], "cancelled")
		self.assertEqual(self._steps(overview)[3], ("payment", "skipped"))

	def test_a_missing_file_comes_before_the_lifecycle(self):
		einvoice = self._einvoice("FLOW-OV-007", content_state="pending")
		self._event(einvoice, "in_hand", "2026-06-02 10:00:00", state="done")

		overview = self._overview(einvoice)

		self.assertEqual(overview["key"], "file_pending")
		self.assertTrue(overview["can_retry_download"])
		self.assertEqual(self._steps(overview)[0], ("received", "warning"))

	def test_an_undelivered_status_comes_first(self):
		# Otherwise the user believes the supplier was told, while the state never moved.
		einvoice = self._einvoice("FLOW-OV-008", content_state="error")
		self._event(einvoice, "in_hand", "2026-06-02 10:00:00", state="done")
		self._event(einvoice, "approved", "2026-06-03 10:00:00", state="error", error_details="401")

		overview = self._overview(einvoice)

		self.assertEqual(overview["key"], "not_delivered")
		self.assertEqual(overview["steps"][2]["state"], "error")
		failed = next(r for r in overview["history"] if r.get("delivery") == "error")
		self.assertEqual(failed["retry_status"], "approved")
		self.assertEqual(failed["error"], "401")

	def test_a_resent_status_clears_the_delivery_failure(self):
		einvoice = self._einvoice("FLOW-OV-009")
		self._event(einvoice, "approved", "2026-06-03 10:00:00", state="error")
		self._event(einvoice, "approved", "2026-06-03 11:00:00", state="done")

		overview = self._overview(einvoice)

		self.assertEqual(overview["key"], "approved")
		self.assertFalse(any(r.get("retry_status") for r in overview["history"]))

	def test_an_invoice_off_platform_says_so(self):
		einvoice = self._einvoice("FLOW-OV-010")
		einvoice.db_set("pa_flow_id", None, update_modified=False)

		overview = self._overview(einvoice)

		self.assertEqual(overview["key"], "off_platform")
		self.assertFalse(overview["can_retry_download"])

	def test_an_outgoing_invoice_has_no_overview(self):
		einvoice = self._einvoice("FLOW-OV-011")
		einvoice.db_set("einvoice_type", "Outgoing", update_modified=False)

		self.assertIsNone(self._overview(einvoice))

	# ------------------------------------------------------------------
	# History
	# ------------------------------------------------------------------
	def test_history_is_newest_first_and_says_who_acted(self):
		einvoice = self._einvoice("FLOW-OV-012")
		self._event(einvoice, "in_hand", "2026-06-02 10:00:00", state="done")
		self._event(einvoice, "completed", "2026-06-04 10:00:00", direction="in", state="done")

		history = self._overview(einvoice)["history"]

		self.assertEqual([r["title"] for r in history], ["Completed", "In Hand", "Invoice received"])
		self.assertEqual(history[0]["actor"], "From the supplier")
		self.assertEqual(history[1]["actor"], "Sent automatically")
		self.assertEqual(history[1]["code"], "204")
		self.assertEqual(history[1]["delivery"], "done")

	# ------------------------------------------------------------------
	# Retry download
	# ------------------------------------------------------------------
	def test_retry_download_queues_the_fetch(self):
		einvoice = self._einvoice("FLOW-OV-013", content_state="error")

		with patch("etransactions.plateforme_agreee.flow._enqueue_content_fetch") as enqueue:
			lifecycle_overview.retry_content_fetch(einvoice.name)

		enqueue.assert_called_once_with(einvoice.name)

	def test_retry_download_refuses_a_fetched_invoice(self):
		einvoice = self._einvoice("FLOW-OV-014")

		with self.assertRaises(frappe.ValidationError):
			lifecycle_overview.retry_content_fetch(einvoice.name)
