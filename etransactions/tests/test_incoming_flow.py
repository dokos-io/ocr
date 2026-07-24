# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Two-phase ingestion of an incoming flow.

An eInvoice is created from the flow metadata first and its original file is
downloaded and parsed afterwards, so a file the platform cannot serve — or the
parser cannot read — leaves a record behind instead of making the flow vanish
until the next hourly poll.
"""

import os
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from etransactions.components.superpdp.models import IncomingFlow
from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice
from etransactions.etransactions.doctype.einvoice_event.einvoice_event import (
	adopt_orphan_events,
	record_event,
)
from etransactions.tests.utils import eTransactionsTestSuite
from etransactions.utils.files import detect_flow_extension

GET_CLIENT = "etransactions.plateforme_agreee.session.get_client"


class _FakePlatformClient:
	"""Returns the bytes we hand it, or raises, on download_flow()."""

	def __init__(self, content: bytes | None = None, error: Exception | None = None):
		self.content = content
		self.error = error
		self.calls = 0

	def download_flow(self, flow_id):
		self.calls += 1
		if self.error:
			raise self.error
		return self.content


class TestFlowExtensionDetection(UnitTestCase):
	def test_pdf_is_detected_from_its_magic_bytes(self):
		self.assertEqual(detect_flow_extension(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), "pdf")
		self.assertEqual(detect_flow_extension(b"\n  %PDF-1.7"), "pdf")

	def test_anything_else_is_treated_as_xml(self):
		self.assertEqual(detect_flow_extension(b'<?xml version="1.0"?><Invoice/>'), "xml")
		self.assertEqual(detect_flow_extension(b"<Invoice/>"), "xml")
		self.assertEqual(detect_flow_extension(b""), "xml")
		self.assertEqual(detect_flow_extension(None), "xml")


class TestIncomingFlowIngestion(eTransactionsTestSuite):
	def setUp(self):
		super().setUp()
		frappe.db.set_default("company", "_Test Company")

	# ------------------------------------------------------------------
	# Fixtures
	# ------------------------------------------------------------------
	def _fixture(self, folder, file_name) -> bytes:
		# get_app_path scrubs its arguments, so the file name is joined separately
		folder_path = frappe.get_app_path("etransactions", "tests", "invoices", folder)
		with open(os.path.join(folder_path, file_name), "rb") as f:
			return f.read()

	def _facturx_pdf(self) -> bytes:
		return self._fixture(
			"1.basic_wl", "Facture_F20220023-LE_FOURNISSEUR-POUR-LE_CLIENT_BASIC_WL.pdf"
		)

	def _flow(self, flow_id, **kwargs) -> IncomingFlow:
		return IncomingFlow(
			flow_id=flow_id,
			submitted_at="2026-06-01 00:00:00",
			updated_at=None,
			flow_type="SupplierInvoice",
			# SuperPDP announces no syntax on an incoming invoice.
			syntax=kwargs.pop("syntax", None),
			**kwargs,
		)

	def _supplier_invoice_of(self, einvoice):
		return frappe.db.get_value("Supplier Invoice", {"einvoice": einvoice.name})

	# ------------------------------------------------------------------
	# Phase 1 — metadata only
	# ------------------------------------------------------------------
	def test_flow_is_recorded_before_its_content_is_available(self):
		flow = self._flow(
			"FLOW-META-001",
			en_invoice={
				"invoice": {
					"invoice_number": "F-2026-77",
					"issue_date": "2026-06-01",
					"invoice_currency_code": "EUR",
					"invoice_total_amount_with_vat": "120.00",
				},
				"seller": {"name": "LE FOURNISSEUR", "vat_identifier": "FR12345678901"},
				"buyer": {"name": "LE CLIENT"},
			},
		)

		einvoice = eInvoice.create_from_plateforme_flow(flow, None, "_Test Company")

		self.assertEqual(einvoice.pa_content_state, "pending")
		self.assertFalse(einvoice.einvoice, "no file should be attached yet")
		# Readable in the inbox straight away, from what the platform returned.
		self.assertEqual(einvoice.id, "F-2026-77")
		self.assertEqual(einvoice.seller_name, "LE FOURNISSEUR")
		self.assertEqual(einvoice.grand_total, 120.0)

	def test_no_supplier_invoice_is_generated_while_content_is_pending(self):
		einvoice = eInvoice.create_from_plateforme_flow(
			self._flow("FLOW-META-002"), None, "_Test Company"
		)

		self.assertFalse(
			self._supplier_invoice_of(einvoice),
			"a metadata-only eInvoice would produce an empty Supplier Invoice",
		)

	# ------------------------------------------------------------------
	# Phase 2 — deferred download and parse
	# ------------------------------------------------------------------
	def test_content_fetch_attaches_parses_and_generates_the_supplier_invoice(self):
		einvoice = eInvoice.create_from_plateforme_flow(
			self._flow("FLOW-FETCH-001"), None, "_Test Company"
		)

		client = _FakePlatformClient(content=self._facturx_pdf())
		with patch(GET_CLIENT, return_value=client):
			einvoice.fetch_content_from_platform()

		einvoice.reload()
		self.assertEqual(einvoice.pa_content_state, "fetched")
		self.assertTrue(einvoice.einvoice)
		# The platform declared no syntax: the extension comes from the bytes, and
		# it has to, because the parser dispatches on it.
		self.assertTrue(frappe.db.get_value("File", einvoice.einvoice, "file_name").endswith(".pdf"))
		self.assertEqual(einvoice.seller_name, "LE FOURNISSEUR")
		self.assertEqual(einvoice.id, "F20220023")
		self.assertTrue(self._supplier_invoice_of(einvoice))

	def test_a_failed_download_leaves_the_invoice_behind_to_retry(self):
		einvoice = eInvoice.create_from_plateforme_flow(
			self._flow("FLOW-FETCH-002"), None, "_Test Company"
		)

		client = _FakePlatformClient(error=Exception("platform unavailable"))
		with patch(GET_CLIENT, return_value=client):
			einvoice.fetch_content_from_platform()

		einvoice.reload()
		self.assertEqual(einvoice.pa_content_state, "error")
		self.assertIn("platform unavailable", einvoice.pa_content_error)
		self.assertTrue(frappe.db.exists("eInvoice", einvoice.name), "the record must survive")

	def test_retry_picks_up_pending_and_errored_flows(self):
		from etransactions.plateforme_agreee.flow import retry_pending_einvoice_content

		einvoice = eInvoice.create_from_plateforme_flow(
			self._flow("FLOW-RETRY-001"), None, "_Test Company"
		)

		with patch("frappe.enqueue") as enqueue:
			retry_pending_einvoice_content()

		enqueued = [call.kwargs.get("einvoice") for call in enqueue.call_args_list]
		self.assertIn(einvoice.name, enqueued)

	def test_poller_records_the_flow_and_defers_the_download(self):
		"""One listing call is enough to land the invoice; the file follows."""
		from etransactions.plateforme_agreee.flow import _ingest_incoming_flow

		flow = self._flow(
			"FLOW-POLL-001",
			en_invoice={"invoice": {"invoice_number": "F-POLL-1"}, "seller": {"name": "ACME"}},
			events=[
				{"id": 31, "status_code": "fr:204", "created_at": "2026-06-01T10:00:00Z"},
				{"id": 32, "status_code": "not-a-known-code", "created_at": "2026-06-01T11:00:00Z"},
			],
		)

		with patch("frappe.enqueue") as enqueue:
			name = _ingest_incoming_flow(flow, "_Test Company")

		einvoice = frappe.get_doc("eInvoice", name)
		self.assertEqual(einvoice.pa_content_state, "pending")
		self.assertEqual(einvoice.id, "F-POLL-1")

		# The events shipped with the listing are stored, unknown codes ignored.
		events = frappe.get_all(
			"eInvoice Event", filters={"einvoice": name}, fields=["pa_event_id", "status"]
		)
		self.assertEqual([e.pa_event_id for e in events], ["31"])
		self.assertEqual(events[0].status, "in_hand")

		fetches = [c for c in enqueue.call_args_list if c.kwargs.get("einvoice") == name]
		self.assertEqual(len(fetches), 1, "the content fetch should be enqueued exactly once")

	# ------------------------------------------------------------------
	# Events arriving before their invoice
	# ------------------------------------------------------------------
	def test_an_event_without_an_invoice_is_claimed_by_flow_id(self):
		orphan = record_event(
			None,
			direction="in",
			status="received",
			pa_event_id="EV-ORPHAN-1",
			pa_flow_id="FLOW-EVENT-001",
		)
		self.assertIsNotNone(orphan)
		self.assertFalse(orphan.einvoice)

		einvoice = eInvoice.create_from_plateforme_flow(
			self._flow("FLOW-EVENT-001"), None, "_Test Company"
		)

		self.assertEqual(frappe.db.get_value("eInvoice Event", orphan.name, "einvoice"), einvoice.name)

	def test_an_adopted_event_is_not_recorded_twice(self):
		record_event(
			None,
			direction="in",
			status="received",
			pa_event_id="EV-ORPHAN-2",
			pa_flow_id="FLOW-EVENT-002",
		)
		eInvoice.create_from_plateforme_flow(self._flow("FLOW-EVENT-002"), None, "_Test Company")

		# The same event polled again, still without knowing the invoice.
		again = record_event(
			None,
			direction="in",
			status="received",
			pa_event_id="EV-ORPHAN-2",
			pa_flow_id="FLOW-EVENT-002",
		)

		self.assertIsNone(again, "dedup must recognise the event it already adopted")
		self.assertEqual(frappe.db.count("eInvoice Event", {"pa_event_id": "EV-ORPHAN-2"}), 1)

	def test_adoption_leaves_events_of_other_flows_alone(self):
		mine = record_event(
			None, direction="in", status="received", pa_event_id="EV-A", pa_flow_id="FLOW-A"
		)
		other = record_event(
			None, direction="in", status="received", pa_event_id="EV-B", pa_flow_id="FLOW-B"
		)

		self.assertEqual(adopt_orphan_events("EINV-A", "FLOW-A"), 1)
		self.assertEqual(frappe.db.get_value("eInvoice Event", mine.name, "einvoice"), "EINV-A")
		self.assertFalse(frappe.db.get_value("eInvoice Event", other.name, "einvoice"))
