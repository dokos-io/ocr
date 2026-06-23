# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from etransactions.plateforme_agreee import sandbox
from etransactions.plateforme_agreee.routing import (
	identifier_to_electronic_address,
	resolve_routing,
)

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTesteTransactionsAccreditedPlatform(IntegrationTestCase):
	"""Integration tests for the SuperPDP sandbox self-test provisioning."""

	def tearDown(self):
		frappe.db.rollback()

	@patch("etransactions.plateforme_agreee.directory.sync_customer_directory")
	def test_provision_is_idempotent_and_routes_deterministically(self, mock_sync):
		# Sync is patched out so the test never reaches the network; the function
		# must still produce a correct, deterministic routing setup on its own.
		mock_sync.return_value = None

		first = sandbox.provision_superpdp_test_customer("Sandbox Co")
		second = sandbox.provision_superpdp_test_customer("Sandbox Co")
		self.assertEqual(first, second, "Re-running provisioning must reuse the same customer")

		customer = frappe.get_doc("Customer", first)
		self.assertEqual(customer.siren_number, sandbox.TEST_SIREN)
		self.assertEqual(customer.directory_type, sandbox.TEST_DIRECTORY_TYPE)
		# Forced private so the invoice is classified B2B (sendable), not B2C.
		self.assertEqual(customer.directory_entity_type, "private")
		self.assertTrue(customer.default_directory_line)

		# Exactly one Tricatel line, active, bound to the test address.
		lines = frappe.get_all(
			"eInvoicing Directory Line",
			filters={"customer": first, "identifier": sandbox.TEST_IDENTIFIER},
			fields=["name", "line_status"],
		)
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0].line_status, "active")
		self.assertEqual(customer.default_directory_line, lines[0].name)

		# Routing resolves to that line and yields the expected Peppol address.
		resolved = resolve_routing("Customer", first)
		self.assertEqual(resolved, lines[0].name)
		scheme, value = identifier_to_electronic_address(sandbox.TEST_IDENTIFIER)
		self.assertEqual((scheme, value), ("0225", "315143296_35"))

	def test_send_rejects_non_sandbox_platform(self):
		platform = frappe.get_doc({
			"doctype": "eTransactions Accredited Platform",
			"platform_name": "SuperPDP Prod Test",
			"platform_type": "SuperPDP",
			"company": frappe.defaults.get_global_default("company") or "_Test Company",
			"transaction_type": "Both",
			"is_active": 1,
			"is_sandbox": 0,
			"client_id": "x",
			"client_secret": "y",
		}).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			sandbox.send_superpdp_test_invoice(platform.name)


class UnitTestSuperPDPStatus(UnitTestCase):
	"""Pure-logic tests for SuperPDP status-code mapping (no DB fixtures)."""

	def test_rejection_status_mapping(self):
		"""A platform rejection (fr:213) maps to 'rejected', not 'pending', and its
		reasons are captured so the eInvoice can surface them."""
		from etransactions.components.superpdp.client import SuperPDPClient

		client = SuperPDPClient("id", "secret")
		self.assertEqual(client._map_code("fr:213"), "rejected")  # Rejected
		self.assertEqual(client._map_code("fr:210"), "rejected")  # Refused
		self.assertEqual(client._map_code("fr:501"), "error")     # Inadmissible
		self.assertEqual(client._map_code("fr:205"), "done")      # Accepted
		self.assertEqual(client._map_code("fr:201"), "pending")   # Sent

		events = [{"status_code": "fr:213", "details": [{"reason": "BR-FR-05/BT-22 missing"}]}]
		self.assertEqual(client._derive_status(events), "rejected")
		self.assertIn("BR-FR-05", client._collect_error_details(events))
