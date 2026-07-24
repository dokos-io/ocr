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
		# The sandbox identifiers are not valid SIRENs (erpnext refuses them), so the
		# customer carries none: addressing comes from the directory line below.
		self.assertFalse(customer.siren_number)
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

	def _superpdp_doc(self, **overrides):
		data = {
			"doctype": "eTransactions Accredited Platform",
			"platform_name": "SuperPDP Conf Test",
			"platform_type": "SuperPDP",
			"company": frappe.defaults.get_global_default("company") or "_Test Company",
			"transaction_type": "Both",
		}
		data.update(overrides)
		return frappe.get_doc(data)

	def test_missing_credentials_blocked(self):
		"""A non-Esalink platform must carry Client ID/Secret on the record."""
		with self.assertRaises(frappe.ValidationError):
			self._superpdp_doc().insert(ignore_permissions=True)

	def test_credentials_required_on_record_no_conf_fallback(self):
		"""site_config keys no longer satisfy the credential requirement."""
		with patch.dict(
			frappe.conf,
			{"superpdp_client_id": "confid", "superpdp_client_secret": "confsec"},
		):
			with self.assertRaises(frappe.ValidationError):
				self._superpdp_doc().insert(ignore_permissions=True)

	def test_platform_credentials_read_doc_only(self):
		"""_platform_credentials returns the record's values and ignores site_config."""
		from etransactions.plateforme_agreee.session import _platform_credentials

		explicit = self._superpdp_doc(client_id="docid", client_secret="docsec").insert(
			ignore_permissions=True
		)
		self.assertEqual(_platform_credentials(explicit), ("docid", "docsec"))

		# Esalink may be saved with blank creds (minted later); the fallback is gone, so a
		# blank record yields (None, None) even when site_config carries matching keys.
		# The partner-config gate is orthogonal to what this test checks, so it's stubbed
		# out to let the blank Esalink row insert.
		with patch(
			"etransactions.plateforme_agreee.esalink_provisioning.partner_credentials_configured",
			return_value=True,
		):
			esalink = frappe.get_doc({
				"doctype": "eTransactions Accredited Platform",
				"platform_name": "Esalink Cred Test",
				"platform_type": "Esalink",
				"company": frappe.defaults.get_global_default("company") or "_Test Company",
				"transaction_type": "Both",
			}).insert(ignore_permissions=True)
		with patch.dict(
			frappe.conf,
			{"esalink_client_id": "confid", "esalink_client_secret": "confsec"},
		):
			self.assertEqual(_platform_credentials(esalink), (None, None))

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


class UnitTestBuildClient(UnitTestCase):
	"""Client-factory logic for the per-platform Esalink environment selector."""

	def test_esalink_environment_drives_base_url(self):
		from etransactions.components.esalink.client import ESALINK_BASE_URLS
		from etransactions.plateforme_agreee import session

		# EsalinkClient authenticates lazily, so construction hits no network.
		# Neutralise the Microcks test seam (active when microcks_url is set in CI)
		# so this asserts the real environment→URL fallback.
		with patch(
			"etransactions.plateforme_agreee._microcks.microcks_base_url", return_value=None
		), patch(
			"etransactions.plateforme_agreee.esalink_provisioning.esalink_api_key",
			return_value="k",
		):
			for env in ("prod", "test"):
				client = session._build_client(
					"Esalink", "u", "p", company="X", esalink_environment=env
				)
				self.assertEqual(client._base_url, ESALINK_BASE_URLS[env].rstrip("/"))

			# No per-platform env → prod. The environment is no longer a site-level setting,
			# so there is nothing else left to fall back to.
			default = session._build_client("Esalink", "u", "p", company="X")
			self.assertEqual(default._base_url, ESALINK_BASE_URLS["prod"].rstrip("/"))
