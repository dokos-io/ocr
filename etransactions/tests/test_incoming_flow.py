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
	"""Returns the bytes we hand it, or raises, on download_flow().

	``download_flow_readable_pdf`` is only exposed as an attribute when the test asks
	for it — real clients duck-type this capability, and some platforms don't have it,
	so the fake has to be able to not have it either.
	"""

	def __init__(
		self,
		content: bytes | None = None,
		error: Exception | None = None,
		readable_pdf: bytes | None = None,
		readable_pdf_error: Exception | None = None,
		supports_readable_pdf: bool = False,
	):
		self.content = content
		self.error = error
		self.calls = 0
		self.readable_pdf = readable_pdf
		self.readable_pdf_error = readable_pdf_error
		self.readable_pdf_calls = 0
		if supports_readable_pdf or readable_pdf is not None or readable_pdf_error is not None:
			self.download_flow_readable_pdf = self._download_flow_readable_pdf

	def download_flow(self, flow_id):
		self.calls += 1
		if self.error:
			raise self.error
		return self.content

	def _download_flow_readable_pdf(self, flow_id):
		self.readable_pdf_calls += 1
		if self.readable_pdf_error:
			raise self.readable_pdf_error
		return self.readable_pdf


class _FakeListingClient:
	"""Answers list_incoming_invoices() with a canned list of flows."""

	def __init__(self, flows):
		self.flows = flows

	def list_incoming_invoices(self, updated_after=None):
		return self.flows


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

	def _ubl_xml(self) -> bytes:
		return self._fixture("5.ubl", "UBL-Invoice-2.1-Example.xml")

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

	# ------------------------------------------------------------------
	# Phase 2b — readable PDF for structured-only (XML) flows
	# ------------------------------------------------------------------
	def test_structured_only_flow_gets_a_readable_pdf(self):
		"""A pure UBL flow has no PDF of its own; if the platform can render one on
		request, it becomes the Supplier Invoice's preview instead of the XML."""
		einvoice = eInvoice.create_from_plateforme_flow(
			self._flow("FLOW-PDF-001"), None, "_Test Company"
		)

		client = _FakePlatformClient(content=self._ubl_xml(), readable_pdf=self._facturx_pdf())
		with patch(GET_CLIENT, return_value=client):
			einvoice.fetch_content_from_platform()

		einvoice.reload()
		self.assertEqual(client.readable_pdf_calls, 1)
		self.assertTrue(einvoice.einvoice_readable_pdf)
		self.assertTrue(frappe.db.get_value("File", einvoice.einvoice, "file_name").endswith(".xml"))

		supplier_invoice_name = self._supplier_invoice_of(einvoice)
		self.assertTrue(supplier_invoice_name)
		supplier_invoice = frappe.get_doc("Supplier Invoice", supplier_invoice_name)
		self.assertTrue(supplier_invoice.file_url.endswith(".pdf"))

	def test_readable_pdf_is_not_requested_for_an_already_pdf_flow(self):
		"""Factur-X already carries its own PDF; no extra platform call is needed."""
		einvoice = eInvoice.create_from_plateforme_flow(
			self._flow("FLOW-PDF-002"), None, "_Test Company"
		)

		client = _FakePlatformClient(
			content=self._facturx_pdf(), readable_pdf=self._facturx_pdf(), supports_readable_pdf=True
		)
		with patch(GET_CLIENT, return_value=client):
			einvoice.fetch_content_from_platform()

		einvoice.reload()
		self.assertEqual(client.readable_pdf_calls, 0)
		self.assertFalse(einvoice.einvoice_readable_pdf)

	def test_no_readable_pdf_capability_falls_back_to_the_xml(self):
		"""A platform that can't render a PDF just leaves the invoice with its XML."""
		einvoice = eInvoice.create_from_plateforme_flow(
			self._flow("FLOW-PDF-003"), None, "_Test Company"
		)

		client = _FakePlatformClient(content=self._ubl_xml())  # no readable-PDF support
		with patch(GET_CLIENT, return_value=client):
			einvoice.fetch_content_from_platform()

		einvoice.reload()
		self.assertEqual(einvoice.pa_content_state, "fetched")
		self.assertFalse(einvoice.einvoice_readable_pdf)
		supplier_invoice_name = self._supplier_invoice_of(einvoice)
		self.assertTrue(frappe.db.get_value("Supplier Invoice", supplier_invoice_name, "file_url").endswith(".xml"))

	def test_readable_pdf_failure_does_not_block_ingestion(self):
		"""The platform erroring on the readable-PDF request must not lose the invoice."""
		einvoice = eInvoice.create_from_plateforme_flow(
			self._flow("FLOW-PDF-004"), None, "_Test Company"
		)

		client = _FakePlatformClient(
			content=self._ubl_xml(), readable_pdf_error=Exception("rendering unavailable")
		)
		with patch(GET_CLIENT, return_value=client):
			einvoice.fetch_content_from_platform()

		einvoice.reload()
		self.assertEqual(einvoice.pa_content_state, "fetched")
		self.assertFalse(einvoice.einvoice_readable_pdf)
		self.assertTrue(self._supplier_invoice_of(einvoice))

	def test_readable_pdf_response_that_is_not_actually_a_pdf_is_discarded(self):
		"""Defend against a platform returning something bogus for docType=ReadableView."""
		einvoice = eInvoice.create_from_plateforme_flow(
			self._flow("FLOW-PDF-005"), None, "_Test Company"
		)

		client = _FakePlatformClient(content=self._ubl_xml(), readable_pdf=b"not a pdf")
		with patch(GET_CLIENT, return_value=client):
			einvoice.fetch_content_from_platform()

		einvoice.reload()
		self.assertFalse(einvoice.einvoice_readable_pdf)

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
	# The poll window must not advance past a flow that failed to ingest
	# ------------------------------------------------------------------
	def _ensure_active_platform(self, company="_Test Company") -> str:
		existing = frappe.db.get_value("eTransactions Accredited Platform", {"company": company})
		if existing:
			frappe.db.set_value(
				"eTransactions Accredited Platform",
				existing,
				{"is_active": 1, "last_incoming_poll": None},
				update_modified=False,
			)
			return existing

		platform = frappe.get_doc({
			"doctype": "eTransactions Accredited Platform",
			"platform_name": "Test Poll Window Platform",
			"platform_type": "Custom",
			"platform_code": "TESTWIN",
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

	def test_a_failed_ingestion_pins_the_poll_window_instead_of_losing_the_flow(self):
		"""A flow whose eInvoice creation fails has no pa_flow_id, so it can never join
		known_flow_ids — normally harmless, because it's still inside next run's window
		and gets retried. But the window is anchored on last_incoming_poll, which used to
		advance unconditionally: two or three failing hourly runs later, the flow falls
		outside "last poll - 1h" and is never listed, and so never retried, again."""
		from etransactions.plateforme_agreee import flow as flow_module

		GET_CLIENT_IN_FLOW = "etransactions.plateforme_agreee.flow.get_client"
		platform_name = self._ensure_active_platform()

		def make_flow(flow_id, submitted_at):
			return IncomingFlow(
				flow_id=flow_id,
				submitted_at=submitted_at,
				updated_at=None,
				flow_type="SupplierInvoice",
				syntax=None,
			)

		good_flow = make_flow("FLOW-WINDOW-GOOD", "2026-06-05 10:00:00")
		bad_flow = make_flow("FLOW-WINDOW-BAD", "2026-06-01 08:00:00")
		client = _FakeListingClient([bad_flow, good_flow])

		real_ingest = flow_module._ingest_incoming_flow

		def ingest_unless_bad(flow, company, platform=None):
			if flow.flow_id == bad_flow.flow_id:
				raise ValueError("simulated ingestion failure")
			return real_ingest(flow, company, platform=platform)

		with (
			patch(GET_CLIENT_IN_FLOW, return_value=client),
			patch.object(flow_module, "_ingest_incoming_flow", side_effect=ingest_unless_bad),
			patch("frappe.enqueue"),
		):
			flow_module.poll_incoming_flows()

		self.assertTrue(
			frappe.db.exists("eInvoice", {"pa_flow_id": good_flow.flow_id}),
			"the flow that succeeded must still be recorded",
		)
		self.assertFalse(
			frappe.db.exists("eInvoice", {"pa_flow_id": bad_flow.flow_id}),
			"the flow that failed must not have an eInvoice",
		)

		last_poll = frappe.db.get_value(
			"eTransactions Accredited Platform", platform_name, "last_incoming_poll"
		)
		self.assertEqual(
			frappe.utils.get_datetime(last_poll),
			frappe.utils.get_datetime(bad_flow.submitted_at),
			"the window must stay pinned at the failed flow's own timestamp, not jump to now",
		)

		# A second run, still failing: the window must not creep forward either.
		with (
			patch(GET_CLIENT_IN_FLOW, return_value=client),
			patch.object(flow_module, "_ingest_incoming_flow", side_effect=ingest_unless_bad),
			patch("frappe.enqueue"),
		):
			flow_module.poll_incoming_flows()

		still_pinned = frappe.db.get_value(
			"eTransactions Accredited Platform", platform_name, "last_incoming_poll"
		)
		self.assertEqual(frappe.utils.get_datetime(still_pinned), frappe.utils.get_datetime(bad_flow.submitted_at))

		# Once the flow finally ingests, the window is free to advance again.
		with (
			patch(GET_CLIENT_IN_FLOW, return_value=client),
			patch("frappe.enqueue"),
		):
			flow_module.poll_incoming_flows()

		self.assertTrue(frappe.db.exists("eInvoice", {"pa_flow_id": bad_flow.flow_id}))
		advanced = frappe.db.get_value(
			"eTransactions Accredited Platform", platform_name, "last_incoming_poll"
		)
		self.assertGreater(frappe.utils.get_datetime(advanced), frappe.utils.get_datetime(bad_flow.submitted_at))

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

	def test_contradictory_incoming_events_are_still_recorded(self):
		# The transition guard applies to what *we* report, never to what the platform
		# tells us: the history has to stay a faithful log, contradictions included.
		einvoice = eInvoice.create_from_plateforme_flow(
			self._flow("FLOW-EVENT-CONTRADICT"), None, "_Test Company"
		)
		record_event(
			einvoice.name, direction="in", status="refused", status_datetime="2026-06-02 10:00:00"
		)

		later = record_event(
			einvoice.name, direction="in", status="approved", status_datetime="2026-06-03 10:00:00"
		)

		self.assertIsNotNone(later, "an inbound event must never be rejected")
		self.assertEqual(
			frappe.db.count("eInvoice Event", {"einvoice": einvoice.name}),
			2,
		)

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
