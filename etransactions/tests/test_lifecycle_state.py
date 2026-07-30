# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""The lifecycle state an eInvoice is in, derived from its recorded events.

This is what the transition guard reads, so how it is computed matters more than it
looks: events are polled with a *platform-supplied* timestamp and can be stored out of
chronological order, and the axis an event belongs to comes from the status rather than
from who sent it.
"""

import frappe

from etransactions.components.superpdp.models import IncomingFlow
from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice
from etransactions.etransactions.doctype.einvoice_event.einvoice_event import (
	current_lifecycle_state,
	record_event,
)
from etransactions.tests.utils import eTransactionsTestSuite


class TestCurrentLifecycleState(eTransactionsTestSuite):
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

	def _event(self, einvoice, status, when, direction="out", **kwargs):
		return record_event(
			einvoice.name, direction=direction, status=status, status_datetime=when, **kwargs
		)

	# ------------------------------------------------------------------
	# The two axes
	# ------------------------------------------------------------------
	def test_each_axis_keeps_its_own_current_status(self):
		einvoice = self._einvoice("FLOW-STATE-001")
		self._event(einvoice, "in_hand", "2026-06-02 10:00:00")
		self._event(einvoice, "completed", "2026-06-03 10:00:00", direction="in")

		state = current_lifecycle_state(einvoice.name)

		self.assertEqual(state["purchase"], "in_hand")
		self.assertEqual(state["sale"], "completed")

	def test_the_axis_comes_from_the_status_not_the_direction(self):
		# A counterparty status arriving inbound still moves the axis it belongs to,
		# otherwise a buyer's refusal of an invoice we issued would go unnoticed.
		einvoice = self._einvoice("FLOW-STATE-002")
		self._event(einvoice, "refused", "2026-06-02 10:00:00", direction="in")

		state = current_lifecycle_state(einvoice.name)

		self.assertEqual(state["purchase"], "refused")
		self.assertTrue(state["refused"])

	def test_a_later_event_on_one_axis_does_not_clear_the_other(self):
		# The refused flag is membership, not recency: a sale-axis event recorded
		# afterwards must not un-refuse the invoice.
		einvoice = self._einvoice("FLOW-STATE-003")
		self._event(einvoice, "refused", "2026-06-02 10:00:00", direction="in")
		self._event(einvoice, "payment_received", "2026-06-04 10:00:00")

		state = current_lifecycle_state(einvoice.name)

		self.assertTrue(state["refused"])
		self.assertEqual(state["purchase"], "refused")

	# ------------------------------------------------------------------
	# Ordering
	# ------------------------------------------------------------------
	def test_an_event_stored_out_of_order_does_not_become_current(self):
		einvoice = self._einvoice("FLOW-STATE-004")
		self._event(einvoice, "approved", "2026-06-05 10:00:00")
		# Polled afterwards, but it happened earlier on the platform.
		self._event(einvoice, "in_hand", "2026-06-01 10:00:00", direction="in")

		self.assertEqual(current_lifecycle_state(einvoice.name)["purchase"], "approved")

	def test_identical_timestamps_are_broken_by_insertion_order(self):
		# A single poll records a whole batch with the same status_datetime.
		einvoice = self._einvoice("FLOW-STATE-005")
		self._event(einvoice, "approved", "2026-06-06 10:00:00", direction="in")
		self._event(einvoice, "dispute", "2026-06-06 10:00:00", direction="in")

		self.assertEqual(current_lifecycle_state(einvoice.name)["purchase"], "dispute")

	# ------------------------------------------------------------------
	# What must not count
	# ------------------------------------------------------------------
	def test_an_errored_event_never_moves_the_state(self):
		einvoice = self._einvoice("FLOW-STATE-006")
		self._event(einvoice, "in_hand", "2026-06-02 10:00:00")
		self._event(einvoice, "approved", "2026-06-03 10:00:00", state="error")

		self.assertEqual(current_lifecycle_state(einvoice.name)["purchase"], "in_hand")

	def test_an_unknown_status_is_ignored(self):
		# `status` is a free Data field fed by the platform.
		einvoice = self._einvoice("FLOW-STATE-007")
		self._event(einvoice, "in_hand", "2026-06-02 10:00:00")
		self._event(einvoice, "teleported", "2026-06-03 10:00:00", direction="in")

		self.assertEqual(current_lifecycle_state(einvoice.name)["purchase"], "in_hand")

	def test_an_invoice_without_events_has_an_empty_state(self):
		einvoice = self._einvoice("FLOW-STATE-008")

		state = current_lifecycle_state(einvoice.name)

		self.assertIsNone(state["purchase"])
		self.assertIsNone(state["sale"])
		self.assertFalse(state["refused"])
		self.assertFalse(state["cancelled"])


class TestLifecycleStatusProjection(eTransactionsTestSuite):
	"""The denormalised eInvoice.lifecycle_status field kept for the list view."""

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

	def _projected(self, einvoice):
		return frappe.db.get_value("eInvoice", einvoice.name, "lifecycle_status")

	def test_recording_an_event_updates_the_projection(self):
		einvoice = self._einvoice("FLOW-PROJ-001")
		record_event(
			einvoice.name, direction="out", status="in_hand", status_datetime="2026-06-02 10:00:00"
		)

		self.assertEqual(self._projected(einvoice), "in_hand")

	def test_the_projection_is_recomputed_not_overwritten(self):
		# An event stored out of order must not become the displayed status either.
		einvoice = self._einvoice("FLOW-PROJ-002")
		record_event(
			einvoice.name, direction="out", status="approved", status_datetime="2026-06-05 10:00:00"
		)
		record_event(
			einvoice.name, direction="in", status="in_hand", status_datetime="2026-06-01 10:00:00"
		)

		self.assertEqual(self._projected(einvoice), "approved")

	def test_adopted_orphan_events_reach_the_projection(self):
		# The adoption UPDATE bypasses the document layer, so the projection has to be
		# refreshed explicitly — otherwise these events would stay invisible.
		record_event(
			None,
			direction="in",
			status="in_hand",
			pa_event_id="EV-PROJ-1",
			pa_flow_id="FLOW-PROJ-003",
			status_datetime="2026-06-02 10:00:00",
		)

		einvoice = self._einvoice("FLOW-PROJ-003")

		self.assertEqual(self._projected(einvoice), "in_hand")
