# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""End-to-end e-invoicing tests across the three PA connection modes.

Each scenario runs against every platform type (Custom/AFNOR, SuperPDP, Esalink)
by switching the active platform and driving the real send/status/directory paths
over HTTP to the Microcks mock. See :mod:`.base` for the harness and skip contract.
"""

from unittest.mock import patch

from etransactions.features import FEATURES
from etransactions.plateforme_agreee.session import get_client
from etransactions.tests.integration.base import (
	BUYER_SIREN,
	PLATFORM_FIXTURES,
	PUBLIC_SIREN,
	MicrocksTestCase,
)

PLATFORM_TYPES = ("Custom", "SuperPDP", "Esalink")


class TestEInvoicingE2E(MicrocksTestCase):
	def test_b2b_send_roundtrips_flow_id(self):
		"""A B2B invoice is submitted over real HTTP and the mock's flow id + sent
		status are persisted — for every connection mode."""
		for ptype in PLATFORM_TYPES:
			with self.subTest(platform=ptype):
				self.use_platform(ptype)
				customer = self.make_customer(
					f"_Test B2B {ptype}", entity_type="private", siren=BUYER_SIREN
				)
				einvoice = self.make_einvoice(customer)
				self.assertEqual(einvoice.pa_processing_rule, "B2B")

				einvoice.send_to_plateform()

				self.assertEqual(einvoice.pa_flow_id, PLATFORM_FIXTURES[ptype]["ok_flow"])
				self.assertEqual(einvoice.pa_status, "sent")

	def test_status_refresh_marks_done(self):
		"""Polling the accepted flow maps the platform ack to a 'done' status."""
		for ptype in PLATFORM_TYPES:
			with self.subTest(platform=ptype):
				self.use_platform(ptype)
				customer = self.make_customer(
					f"_Test B2B {ptype}", entity_type="private", siren=BUYER_SIREN
				)
				einvoice = self.make_einvoice(customer)
				einvoice.send_to_plateform()

				einvoice.refresh_pa_status()
				self.assertEqual(einvoice.pa_status, "done")

	def test_status_refresh_marks_rejected(self):
		"""A failed flow surfaces as a problem status with the platform's reason text.

		SuperPDP distinguishes 'rejected'; CDAR platforms (AFNOR/Esalink) only expose
		an 'Error' acknowledgement, mapped to 'error' — both carry the reason.
		"""
		for ptype in PLATFORM_TYPES:
			with self.subTest(platform=ptype):
				self.use_platform(ptype)
				customer = self.make_customer(
					f"_Test B2B {ptype}", entity_type="private", siren=BUYER_SIREN
				)
				einvoice = self.make_einvoice(customer)
				einvoice.send_to_plateform()
				# Point the flow at the mock's rejected id and re-poll.
				einvoice.db_set("pa_flow_id", PLATFORM_FIXTURES[ptype]["rejected_flow"])

				einvoice.refresh_pa_status()
				self.assertIn(einvoice.pa_status, ("rejected", "error"))
				self.assertTrue(einvoice.pa_error_details)

	def test_b2g_classification_and_send(self):
		"""A public buyer is classified B2G and still sends over HTTP."""
		for ptype in PLATFORM_TYPES:
			with self.subTest(platform=ptype):
				self.use_platform(ptype)
				customer = self.make_customer(
					f"_Test B2G {ptype}", entity_type="public", siren=PUBLIC_SIREN
				)
				einvoice = self.make_einvoice(customer, profile="EXTENDED CTC-FR")
				self.assertEqual(einvoice.pa_processing_rule, "B2G")

				einvoice.send_to_plateform()
				self.assertEqual(einvoice.pa_status, "sent")
				self.assertTrue(einvoice.pa_flow_id)

	def test_ubl_peppol_send_raw_xml(self):
		"""A Peppol customer routes the eInvoice through UBL; the raw XML is sent."""
		# Peppol is opt-in: without the feature every invoice is Factur-X.
		features = {key: int(key == "peppol") for key in FEATURES}
		for ptype in PLATFORM_TYPES:
			with (
				self.subTest(platform=ptype),
				patch("etransactions.features.get_enabled_features", return_value=features),
			):
				self.use_platform(ptype)
				customer = self.make_customer(
					f"_Test Peppol {ptype}",
					entity_type="private",
					siren=BUYER_SIREN,
					directory_type="peppol",
				)
				einvoice = self.make_einvoice(customer, attach_pdf=False)
				self.assertEqual(einvoice.syntax, "UBL")

				einvoice.send_to_plateform()
				self.assertEqual(einvoice.pa_status, "sent")
				self.assertEqual(einvoice.pa_flow_id, PLATFORM_FIXTURES[ptype]["ok_flow"])

	def test_directory_lookup_over_http(self):
		"""get_directory_for_siren resolves an active private routing line from the mock."""
		for ptype in PLATFORM_TYPES:
			with self.subTest(platform=ptype):
				self.use_platform(ptype)
				client = get_client("_Test Company")
				data = client.get_directory_for_siren(BUYER_SIREN)
				self.assertEqual(data.entity_type, "private")
				self.assertIn(BUYER_SIREN, data.lines)

	def test_incoming_flow_roundtrip(self):
		"""Listing + downloading an incoming flow works over HTTP for CDAR platforms."""
		for ptype in ("Custom", "Esalink"):
			with self.subTest(platform=ptype):
				self.use_platform(ptype, transaction_type="Both")
				client = get_client("_Test Company", transaction_type="purchases")
				incoming = client.list_incoming_invoices()
				self.assertTrue(incoming, "mock should return one incoming SupplierInvoice flow")
				content = client.download_flow(incoming[0].flow_id)
				self.assertTrue(content)

	def test_healthcheck_authenticates(self):
		"""healthcheck() performs the real auth handshake against the mock."""
		for ptype in PLATFORM_TYPES:
			with self.subTest(platform=ptype):
				self.use_platform(ptype)
				client = get_client("_Test Company")
				client.healthcheck()  # must not raise
