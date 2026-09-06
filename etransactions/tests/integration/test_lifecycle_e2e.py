# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Buyer-side lifecycle reporting end to end, over real HTTP to the Microcks mock.

The scenario under test is a **refusal** (MDT-105 210): the one status a buyer sends
that is both irreversible and mandatory-with-a-reason (schematron BR-FR-CDV-15, whose
reason list is closed by BR-FR-CDV-CL-09). Everything on the way — CDAR generation,
the AFNOR flow submission, the recorded event — is exercised for real.

Only the CDAR platforms run here. SuperPDP has no ``fr:`` code for ``refused``
(``STATUSES["refused"]["superpdp"] is None``), so ``to_superpdp_code`` throws by
design and there is nothing to send.

See :mod:`.base` for the harness and the skip contract.
"""

from unittest.mock import patch

import frappe

from etransactions.plateforme_agreee import lifecycle_status
from etransactions.tests.integration.base import MicrocksTestCase

# CDAR platforms only: the AFNOR client carries every MDT-105 status as a CDAR flow.
PLATFORM_TYPES = ("Custom", "Esalink")


class TestLifecycleE2E(MicrocksTestCase):
	def _events(self, einvoice, **filters):
		return frappe.get_all(
			"eInvoice Event",
			filters={"einvoice": einvoice.name, **filters},
			fields=["status", "direction", "reason_code", "state"],
		)

	# ------------------------------------------------------------------
	# The refusal reaches the platform
	# ------------------------------------------------------------------
	def test_refusal_submits_a_cdar_over_http(self):
		for ptype in PLATFORM_TYPES:
			with self.subTest(platform=ptype):
				self.use_platform(ptype)
				einvoice = self.make_incoming_einvoice(flow_id=f"LC-REFUSE-{ptype}")

				einvoice.submit_lifecycle_status("refused", reason_code="NON_CONFORME")

				events = self._events(einvoice, status="refused", direction="out")
				self.assertEqual(len(events), 1, "the refusal was not recorded")
				self.assertEqual(events[0].reason_code, "NON_CONFORME")
				self.assertTrue(
					frappe.db.exists(
						"eInvoicing Log", {"operation_type": "lifecycle_send", "origin": "Manual"}
					)
				)

	def test_the_cdar_carries_the_refusal_codes(self):
		"""MDT-105 = 210 and MDT-113 = the reason are what the platform reads.

		The spy is a pass-through, not a mock: it captures the bytes and then calls the
		real ``submit_flow``, so the HTTP round-trip still happens. Replacing the
		transport would break this suite's whole premise.
		"""
		from etransactions.components.afnor.client import AFNORClient

		self.use_platform("Esalink")
		einvoice = self.make_incoming_einvoice(flow_id="LC-CDAR-PAYLOAD")
		captured = []
		original = AFNORClient.submit_flow

		def spy(self, content, filename, flow_type, **kwargs):
			captured.append((content, flow_type))
			return original(self, content, filename, flow_type, **kwargs)

		with patch.object(AFNORClient, "submit_flow", spy):
			einvoice.submit_lifecycle_status("refused", reason_code="TX_TVA_ERR")

		self.assertEqual(len(captured), 1)
		content, flow_type = captured[0]
		self.assertEqual(flow_type, "CDAR")
		xml = content.decode("utf-8")
		self.assertIn("210", xml, "MDT-105 (status code) missing from the CDAR")
		self.assertIn("TX_TVA_ERR", xml, "MDT-113 (reason code) missing from the CDAR")

	# ------------------------------------------------------------------
	# The question this work started from
	# ------------------------------------------------------------------
	def test_an_invoice_can_be_refused_without_a_prior_receipt(self):
		"""Refusal does not require 'In Hand' (204) to have been reported first.

		Neither the CDAR schematron nor the state machine imposes an order — each status
		message is self-contained — and a buyer who spots a bad invoice on arrival should
		not have to acknowledge it before rejecting it.
		"""
		for ptype in PLATFORM_TYPES:
			with self.subTest(platform=ptype):
				self.use_platform(ptype)
				einvoice = self.make_incoming_einvoice(flow_id=f"LC-NO-RECEIPT-{ptype}")

				self.assertEqual(
					self._events(einvoice, status="in_hand"), [], "precondition: no receipt reported"
				)
				self.assertIsNone(einvoice.lifecycle_transition_error("refused"))

				einvoice.submit_lifecycle_status("refused", reason_code="DOUBLON")

				self.assertEqual(len(self._events(einvoice, status="refused")), 1)

	# ------------------------------------------------------------------
	# What must never reach the platform
	# ------------------------------------------------------------------
	def test_a_second_refusal_is_refused_locally(self):
		"""A refusal is terminal, and the guard runs before the network, not after."""
		self.use_platform("Esalink")
		einvoice = self.make_incoming_einvoice(flow_id="LC-DOUBLE-REFUSE")
		einvoice.submit_lifecycle_status("refused", reason_code="NON_CONFORME")

		with patch(
			"etransactions.components.afnor.client.AFNORClient.submit_flow"
		) as submit_flow:
			with self.assertRaises(frappe.ValidationError):
				einvoice.submit_lifecycle_status("refused", reason_code="NON_CONFORME")

		submit_flow.assert_not_called()
		self.assertEqual(len(self._events(einvoice, status="refused")), 1)

	def test_an_invalid_reason_code_never_reaches_the_platform(self):
		"""BR-FR-CDV-CL-09 is a closed list; we enforce our copy of it before sending.

		This is what makes the picker's shape a pure UX choice: whatever the client
		sends, only a code from the schematron's list can leave the server.
		"""
		self.use_platform("Esalink")
		einvoice = self.make_incoming_einvoice(flow_id="LC-BAD-REASON")

		with patch(
			"etransactions.components.afnor.client.AFNORClient.submit_flow"
		) as submit_flow:
			with self.assertRaises(frappe.ValidationError):
				einvoice.submit_lifecycle_status("refused", reason_code="NOT_A_CODE")
			with self.assertRaises(frappe.ValidationError):
				einvoice.submit_lifecycle_status("refused")

		submit_flow.assert_not_called()
		self.assertEqual(self._events(einvoice, status="refused"), [])

	def test_superpdp_cannot_carry_a_refusal(self):
		"""Explicit rather than implied by this module's platform list.

		If SuperPDP ever gains an fr: code for 210, this test fails and points at the
		PLATFORM_TYPES above.
		"""
		self.assertIsNone(lifecycle_status.STATUSES["refused"]["superpdp"])
		self.use_platform("SuperPDP")
		einvoice = self.make_incoming_einvoice(flow_id="LC-SUPERPDP-REFUSE")

		with self.assertRaises(frappe.ValidationError):
			einvoice.submit_lifecycle_status("refused", reason_code="NON_CONFORME")
