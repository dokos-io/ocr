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

	def test_no_active_platform_leaves_a_comment_not_silence(self):
		"""A company with no active platform yet must not vanish without a trace.

		Regression guard: this used to return silently, with no comment, no log entry,
		and no error — the only way to notice was to compare timestamps across three
		different doctypes after the fact.
		"""
		einvoice = self._einvoice("FLOW-AUTO-008")

		with patch("frappe.log_error") as log_error:
			client = self._run(einvoice, "in_hand", platform_type=None)

		self.assertEqual(client.sent, [])
		log_error.assert_not_called()
		comments = self._comments(einvoice)
		self.assertTrue(comments, "the skip should leave an audit trail on the eInvoice")
		self.assertIn("In Hand", comments[0])

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

	def _router(self, values):
		looked_up = []

		def router(doctype, name, fieldname=None, *args, **kwargs):
			looked_up.append((doctype, fieldname))
			return values.get((doctype, fieldname))

		return router, looked_up

	def test_the_purchase_invoice_link_is_used_directly(self):
		router, looked_up = self._router(
			{
				("Purchase Invoice", "einvoice"): "EINV-1",
				("eInvoice", "pa_flow_id"): "FLOW-1",
			}
		)

		with patch("frappe.db.get_value", side_effect=router):
			self.assertEqual(einvoice_for_purchase_invoice("PINV-1"), "EINV-1")

		# The direct link makes the Supplier Invoice hop unnecessary.
		self.assertNotIn(("Supplier Invoice", "einvoice"), looked_up)

	def test_the_chain_falls_back_through_supplier_invoice(self):
		router, looked_up = self._router(
			{
				("Purchase Invoice", "einvoice"): None,
				("Purchase Invoice", "supplier_invoice"): "SINV-1",
				("Supplier Invoice", "einvoice"): "EINV-1",
				("eInvoice", "pa_flow_id"): "FLOW-1",
			}
		)

		with patch("frappe.db.get_value", side_effect=router):
			self.assertEqual(einvoice_for_purchase_invoice("PINV-1"), "EINV-1")

		self.assertIn(("Purchase Invoice", "supplier_invoice"), looked_up)
		self.assertIn(("Supplier Invoice", "einvoice"), looked_up)

	def test_an_einvoice_without_a_flow_id_is_shown_but_not_reported(self):
		"""An e-invoice received by email has no flow id: display yes, lifecycle send no."""
		router, _ = self._router(
			{
				("Purchase Invoice", "einvoice"): "EINV-1",
				("eInvoice", "pa_flow_id"): None,
			}
		)

		with patch("frappe.db.get_value", side_effect=router):
			self.assertEqual(einvoice_for_purchase_invoice("PINV-1"), "EINV-1")
			self.assertIsNone(einvoice_for_purchase_invoice("PINV-1", require_flow_id=True))

	def test_an_invoice_without_an_einvoice_resolves_to_nothing(self):
		# Runs the real SQL: a query against a column that no longer exists would raise
		# here even though nothing matches.
		self.assertIsNone(einvoice_for_purchase_invoice("PINV-DOES-NOT-EXIST"))

	def test_the_transaction_lookup_does_not_raise(self):
		doc = SimpleNamespace(check_permission=lambda perm: None)
		with patch("frappe.get_doc", return_value=doc):
			self.assertIsNone(get_transaction_einvoice("Purchase Invoice", "PINV-DOES-NOT-EXIST"))


class TestEInvoicePanel(eTransactionsTestSuite):
	"""The post-send panel shared by Sales and Purchase Invoice.

	Regression guard: the panel used to be a Sales-Invoice-only endpoint, so the purchase
	form called it with a Purchase Invoice name and the server raised DoesNotExistError on
	``frappe.get_doc("Sales Invoice", "ACC-PINV-…")`` — a traceback dialog over every
	submitted purchase invoice, and no platform status shown for purchases at all.
	"""

	def test_a_purchase_invoice_does_not_hit_the_sales_invoice_table(self):
		from etransactions.plateforme_agreee.readiness import get_einvoice_panel

		read = []

		def get_doc(doctype, name, *args, **kwargs):
			read.append(doctype)
			return SimpleNamespace(check_permission=lambda perm: None)

		with patch("frappe.get_doc", side_effect=get_doc):
			panel = get_einvoice_panel("Purchase Invoice", "PINV-DOES-NOT-EXIST")

		self.assertEqual(read, ["Purchase Invoice"])
		self.assertIsNone(panel["einvoice"])
		self.assertEqual(panel["problems"], [])

	def test_a_purchase_invoice_reports_the_platform_status_of_its_einvoice(self):
		einvoice = frappe.get_doc(
			{
				"doctype": "eInvoice",
				"einvoice_type": "Incoming",
				"company": "_Test Company",
				"pa_flow_id": "FLOW-PANEL-1",
				"pa_status": "rejected",
				"pa_content_state": "fetched",
			}
		).insert(ignore_permissions=True)

		doc = SimpleNamespace(check_permission=lambda perm: None)
		with (
			patch("frappe.get_doc", return_value=doc),
			patch(
				"etransactions.etransactions.doctype.einvoice.einvoice.einvoice_for_transaction",
				return_value=einvoice.name,
			),
		):
			from etransactions.plateforme_agreee.readiness import get_einvoice_panel

			panel = get_einvoice_panel("Purchase Invoice", "PINV-1")

		self.assertEqual(panel["einvoice"], einvoice.name)
		self.assertEqual(panel["pa_status"], "rejected")
		self.assertEqual(panel["pa_flow_id"], "FLOW-PANEL-1")
