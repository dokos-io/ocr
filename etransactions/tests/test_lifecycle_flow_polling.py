# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Incoming CDAR lifecycle flows (Esalink/AFNOR) and the eInvoice each one reports on.

A CDAR is a flow of its own: it names its invoice only by number, and its flow type
says which side of the exchange that invoice is on. Both have to be honoured for the
status to land on the right eInvoice, now or once the invoice exists.
"""

from unittest.mock import patch

import frappe

from etransactions.components.superpdp.models import IncomingFlow, StatusResult
from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice
from etransactions.etransactions.doctype.einvoice_event.einvoice_event import record_event
from etransactions.plateforme_agreee import flow as flow_module
from etransactions.tests.utils import eTransactionsTestSuite

GET_CLIENT_IN_FLOW = "etransactions.plateforme_agreee.flow.get_client"


class _FakeLifecycleClient:
	"""Serves CDAR flows whose content is their own id, so parse_cdar can be faked per flow."""

	def __init__(self, flows: list[IncomingFlow] | None = None, acks: dict[str, StatusResult] | None = None):
		self.flows = flows or []
		self.acks = acks or {}
		self.downloads: list[str] = []
		self.ack_reads: list[str] = []

	def list_incoming_lifecycle_flows(self):
		return self.flows

	def download_flow(self, flow_id):
		self.downloads.append(flow_id)
		return flow_id.encode()

	def get_invoice_status(self, flow_id):
		self.ack_reads.append(flow_id)
		return self.acks[flow_id]


class TestLifecycleFlowPolling(eTransactionsTestSuite):
	def setUp(self):
		super().setUp()
		frappe.db.set_default("company", "_Test Company")
		self._ensure_active_platform()
		# Flow ids are unique per run: the "unsupported code" mark lives in the cache,
		# which a test rollback does not reset.
		self.run_id = frappe.generate_hash(length=8)
		self.cdars: dict[str, dict] = {}

	# ------------------------------------------------------------------
	# Fixtures
	# ------------------------------------------------------------------
	def _ensure_active_platform(self, company="_Test Company") -> str:
		existing = frappe.db.get_value("eTransactions Accredited Platform", {"company": company})
		if existing:
			frappe.db.set_value("eTransactions Accredited Platform", existing, "is_active", 1)
			return existing

		platform = frappe.get_doc({
			"doctype": "eTransactions Accredited Platform",
			"platform_name": "Test Lifecycle Platform",
			"platform_type": "Custom",
			"platform_code": "TESTLC",
			"company": company,
			"transaction_type": "Both",
			"is_active": 1,
			"api_base_url": "http://localhost:1/never-called",
			"client_id": "test",
			"client_secret": "test-secret",
		})
		platform.flags.ignore_permissions = True
		platform.insert()
		return platform.name

	def _einvoice(self, *, einvoice_type="Incoming", id=None, supplier_siren=None):
		einvoice = eInvoice.create_from_plateforme_flow(
			IncomingFlow(
				flow_id=f"INV-{frappe.generate_hash(length=8)}",
				submitted_at="2026-06-01 00:00:00",
				updated_at=None,
				flow_type="SupplierInvoice",
				syntax=None,
			),
			None,
			"_Test Company",
		)
		# Only the columns the lookup reads: an outgoing eInvoice built for real needs a
		# whole Sales Invoice behind it.
		einvoice.db_set(
			{"einvoice_type": einvoice_type, "id": id, "supplier_siren": supplier_siren},
			update_modified=False,
		)
		return einvoice

	def _cdar(
		self, name, flow_type, invoice_number, status_code="205", issuer=None, reason_code=None
	) -> IncomingFlow:
		flow_id = f"CDAR-{self.run_id}-{name}"
		self.cdars[flow_id] = {
			"status_code": status_code,
			"invoice_number": invoice_number,
			"invoice_issuer": issuer,
			"lc_datetime": "2026-06-02 10:00:00",
			"doc_status": [{"reason_code": reason_code}] if reason_code else [],
		}
		return IncomingFlow(
			flow_id=flow_id, submitted_at="2026-06-02 10:00:00", updated_at=None, flow_type=flow_type, syntax="CDAR"
		)

	def _poll(self, *flows) -> _FakeLifecycleClient:
		client = _FakeLifecycleClient(list(flows))
		with (
			patch(GET_CLIENT_IN_FLOW, return_value=client),
			patch("pyfrctc.parse_cdar", side_effect=lambda content: self.cdars[content.decode()]),
		):
			flow_module.poll_incoming_lifecycle_flows()
		return client

	def _event_of(self, flow: IncomingFlow):
		return frappe.db.get_value(
			"eInvoice Event", {"pa_event_id": flow.flow_id}, ["name", "einvoice", "status"], as_dict=True
		)

	# ------------------------------------------------------------------
	# Matching the invoice
	# ------------------------------------------------------------------
	def test_a_status_lands_on_the_side_its_flow_type_names(self):
		number = f"F-SAME-{self.run_id}"
		ours = self._einvoice(einvoice_type="Outgoing", id=number)
		theirs = self._einvoice(einvoice_type="Incoming", id=number)
		about_ours = self._cdar("ours", "CustomerInvoiceLC", number)
		about_theirs = self._cdar("theirs", "SupplierInvoiceLC", number)

		self._poll(about_ours, about_theirs)

		self.assertEqual(self._event_of(about_ours).einvoice, ours.name)
		self.assertEqual(self._event_of(about_theirs).einvoice, theirs.name)

	def test_two_suppliers_sharing_a_number_are_told_apart_by_the_issuer(self):
		number = f"F-TWIN-{self.run_id}"
		self._einvoice(id=number, supplier_siren="111111111")
		second = self._einvoice(id=number, supplier_siren="222222222")
		cdar = self._cdar("twin", "SupplierInvoiceLC", number, issuer="222222222")

		self._poll(cdar)

		self.assertEqual(self._event_of(cdar).einvoice, second.name)

	# ------------------------------------------------------------------
	# Statuses that arrive before their invoice
	# ------------------------------------------------------------------
	def test_a_status_polled_before_the_invoice_number_is_claimed_once_it_is_known(self):
		number = f"F-LATE-{self.run_id}"
		einvoice = self._einvoice()  # the flow is known, its file not parsed yet
		cdar = self._cdar("late", "SupplierInvoiceLC", number, status_code="210")

		self._poll(cdar)
		self.assertFalse(self._event_of(cdar).einvoice, "no eInvoice has this number yet")

		einvoice.reload()
		einvoice.id = number
		einvoice.flags.ignore_permissions = True
		einvoice.save()

		self.assertEqual(self._event_of(cdar).einvoice, einvoice.name)
		self.assertEqual(frappe.db.get_value("eInvoice", einvoice.name, "lifecycle_status"), "refused")
		self.assertTrue(
			frappe.db.exists("ToDo", {"reference_type": "eInvoice", "reference_name": einvoice.name}),
			"an adopted refusal must raise the same ToDo as one recorded directly",
		)

	def test_an_orphan_recorded_without_its_reference_is_completed_on_the_next_poll(self):
		number = f"F-OLD-{self.run_id}"
		einvoice = self._einvoice(id=number)
		cdar = self._cdar("old", "SupplierInvoiceLC", number)
		# What the previous version stored: the CDAR's own flow id and nothing else.
		record_event(None, direction="in", status="approved", pa_event_id=cdar.flow_id, pa_flow_id=cdar.flow_id)

		self._poll(cdar)

		self.assertEqual(self._event_of(cdar).einvoice, einvoice.name)
		self.assertEqual(frappe.db.count("eInvoice Event", {"pa_event_id": cdar.flow_id}), 1)

	# ------------------------------------------------------------------
	# Nothing dropped silently
	# ------------------------------------------------------------------
	def test_an_unsupported_status_code_is_reported_once_and_not_downloaded_again(self):
		cdar = self._cdar("odd", "CustomerInvoiceLC", f"F-ODD-{self.run_id}", status_code="999")

		first = self._poll(cdar)
		second = self._poll(cdar)

		self.assertEqual(first.downloads, [cdar.flow_id])
		self.assertEqual(second.downloads, [], "the flow must not be downloaded on every run")
		self.assertFalse(self._event_of(cdar))
		warnings = frappe.get_all(
			"eInvoicing Log",
			filters={"operation_type": "lifecycle_receive", "logs": ["like", f"%{cdar.flow_id}%999%"]},
		)
		self.assertEqual(len(warnings), 1)

	def test_a_company_whose_client_cannot_be_built_is_logged(self):
		einvoice = self._einvoice(einvoice_type="Outgoing", id=f"F-NOCLIENT-{self.run_id}")
		einvoice.db_set({"pa_status": "sent"}, update_modified=False)
		failures = {"company": "_Test Company", "operation_type": "flow_status", "status": "failure"}
		before = frappe.db.count("eInvoicing Log", failures)

		with patch(GET_CLIENT_IN_FLOW, side_effect=RuntimeError("bad credentials")):
			flow_module.poll_pending_outgoing_flows()

		self.assertEqual(frappe.db.count("eInvoicing Log", failures), before + 1)

	# ------------------------------------------------------------------
	# Statuses set by the platforms (200-203, 213, 501)
	# ------------------------------------------------------------------
	def test_a_rejection_is_recorded_with_its_reason_and_raises_a_todo(self):
		number = f"F-REJ-{self.run_id}"
		einvoice = self._einvoice(einvoice_type="Outgoing", id=number)
		cdar = self._cdar("rej", "CustomerInvoiceLC", number, status_code="213", reason_code="REJ_SEMAN")

		self._poll(cdar)

		event = frappe.db.get_value(
			"eInvoice Event", {"pa_event_id": cdar.flow_id}, ["einvoice", "status", "reason_code"], as_dict=True
		)
		self.assertEqual((event.einvoice, event.status, event.reason_code), (einvoice.name, "rejected", "REJ_SEMAN"))
		self.assertEqual(frappe.db.get_value("eInvoice", einvoice.name, "lifecycle_status"), "rejected")
		self.assertTrue(frappe.db.exists("ToDo", {"reference_type": "eInvoice", "reference_name": einvoice.name}))

	def test_a_rejected_invoice_is_cancelled_without_reporting_a_status(self):
		from etransactions.overrides.sales_invoice import _transmitted_einvoice

		number = f"F-REJCANCEL-{self.run_id}"
		sales_invoice = f"SINV-{self.run_id}"
		einvoice = self._einvoice(einvoice_type="Outgoing", id=number)
		einvoice.db_set({"sales_invoice": sales_invoice, "pa_status": "done"}, update_modified=False)
		self.assertTrue(_transmitted_einvoice(sales_invoice), "an accepted invoice is live on the platform")

		self._poll(self._cdar("rejcancel", "CustomerInvoiceLC", number, status_code="213"))

		self.assertIsNone(
			_transmitted_einvoice(sales_invoice),
			"a 'Cancelled' status would be refused for an invoice the platform rejected",
		)

	def test_transmission_statuses_do_not_block_business_statuses(self):
		number = f"F-PATH-{self.run_id}"
		einvoice = self._einvoice(id=number)
		self._poll(
			self._cdar("p202", "SupplierInvoiceLC", number, status_code="202"),
			self._cdar("p203", "SupplierInvoiceLC", number, status_code="203"),
		)

		self.assertIsNone(einvoice.lifecycle_transition_error("approved"))

	# ------------------------------------------------------------------
	# Acknowledgement of the statuses we send as CDAR flows
	# ------------------------------------------------------------------
	def _sent_status(self, einvoice, status, cdar_flow_id, **kwargs):
		return record_event(
			einvoice.name, direction="out", status=status, state="sent", pa_flow_id=cdar_flow_id, **kwargs
		)

	def _poll_acks(self, acks: dict) -> _FakeLifecycleClient:
		client = _FakeLifecycleClient(acks=acks)
		with patch(GET_CLIENT_IN_FLOW, return_value=client):
			flow_module.poll_outgoing_lifecycle_acknowledgements()
		return client

	def test_an_accepted_status_is_marked_delivered(self):
		einvoice = self._einvoice(einvoice_type="Outgoing", id=f"F-ACK-{self.run_id}")
		cdar_flow = f"OUT-{self.run_id}-ok"
		event = self._sent_status(einvoice, "payment_received", cdar_flow)

		self._poll_acks({cdar_flow: StatusResult(status="done")})

		self.assertEqual(frappe.db.get_value("eInvoice Event", event.name, "state"), "done")

	def test_a_status_the_platform_turned_down_is_marked_undelivered_and_can_be_sent_again(self):
		einvoice = self._einvoice(id=f"F-NACK-{self.run_id}")
		cdar_flow = f"OUT-{self.run_id}-ko"
		event = self._sent_status(einvoice, "refused", cdar_flow, reason_code="DOUBLON")
		self.assertTrue(einvoice.lifecycle_transition_error("approved"), "a refusal blocks everything after it")

		self._poll_acks({cdar_flow: StatusResult(status="error", error_details="Schematron BR-FR-CDV-01")})

		state, details = frappe.db.get_value("eInvoice Event", event.name, ["state", "error_details"])
		self.assertEqual(state, "error")
		self.assertIn("BR-FR-CDV-01", details)
		self.assertIsNone(
			einvoice.lifecycle_transition_error("refused"),
			"an undelivered refusal never reached the supplier, so it must be possible to send it again",
		)

	def test_a_pending_acknowledgement_leaves_the_status_as_sent(self):
		einvoice = self._einvoice(einvoice_type="Outgoing", id=f"F-WAIT-{self.run_id}")
		cdar_flow = f"OUT-{self.run_id}-wait"
		event = self._sent_status(einvoice, "completed", cdar_flow)

		self._poll_acks({cdar_flow: StatusResult(status="pending")})

		self.assertEqual(frappe.db.get_value("eInvoice Event", event.name, "state"), "sent")

	def test_native_platform_events_are_not_polled(self):
		# SuperPDP: an event id, and the invoice's own flow id.
		einvoice = self._einvoice(einvoice_type="Outgoing", id=f"F-NATIVE-{self.run_id}")
		self._sent_status(einvoice, "completed", einvoice.pa_flow_id, pa_event_id=f"EV-{self.run_id}")

		client = self._poll_acks({})

		self.assertNotIn(einvoice.pa_flow_id, client.ack_reads)
