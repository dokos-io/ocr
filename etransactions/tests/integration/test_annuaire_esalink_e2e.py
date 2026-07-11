# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""End-to-end French annuaire (directory) registration via Esalink.

Drives account provisioning (POST /v1/customerPA → mint user), the activation
status poll, and directory-identifier register/list/remove over real HTTP to the
Microcks Esalink Customer API mock. See :mod:`.base` for the harness/skip contract.
"""

import frappe

from etransactions.plateforme_agreee import esalink_provisioning as prov
from etransactions.tests.integration.base import COMPANY, MicrocksTestCase


class TestAnnuaireEsalinkE2E(MicrocksTestCase):
	def test_register_company_provisions_account(self):
		"""register_esalink_company creates the account, mints creds and writes the row."""
		result = prov.register_esalink_company(COMPANY, transaction_type="Both")

		self.assertEqual(result["state"], "created")
		self.assertEqual(result["customer_id"], "777")
		self.assertEqual(result["status"], "WAITING_VALIDATION")

		platform = result["platform_name"]
		row = frappe.db.get_value(
			"eTransactions Accredited Platform",
			platform,
			["platform_type", "esalink_customer_id", "esalink_user_id", "esalink_customer_status", "is_active"],
			as_dict=True,
		)
		self.assertEqual(row.platform_type, "Esalink")
		self.assertEqual(row.esalink_customer_id, "777")
		self.assertEqual(row.esalink_user_id, "mock-esalink-client-id")
		self.assertEqual(row.esalink_customer_status, "WAITING_VALIDATION")
		self.assertEqual(row.is_active, 0)

	def test_status_poll_activates_platform(self):
		"""Refreshing the account status flips the platform active once Esalink reports ACTIVE."""
		result = prov.register_esalink_company(COMPANY)
		platform = result["platform_name"]

		status = prov.refresh_customer_status(platform)
		self.assertEqual(status["status"], "ACTIVE")

		row = frappe.db.get_value(
			"eTransactions Accredited Platform",
			platform,
			["esalink_customer_status", "is_active"],
			as_dict=True,
		)
		self.assertEqual(row.esalink_customer_status, "ACTIVE")
		self.assertEqual(row.is_active, 1)

	def test_directory_identifier_register_list_remove(self):
		"""Register, list and remove a French directory identifier over HTTP."""
		from etransactions.plateforme_agreee import own_directory

		platform = self.use_platform("Esalink")  # carries esalink_customer_id 777

		created = own_directory.register_directory_entry(platform, "0225:824710776", "ppf")
		self.assertEqual(created["directory"], "ppf")
		self.assertEqual(created["identifier"], "824710776")

		entries = own_directory.list_directory_entries(platform)
		self.assertTrue(any(e["identifier"] == "824710776" for e in entries))

		# Remove must round-trip without error (mock returns 200).
		own_directory.remove_directory_entry(platform, "0225:824710776")

	def test_resend_kyc_email(self):
		"""Re-sending the KYC onboarding email round-trips to the partner API."""
		result = prov.register_esalink_company(COMPANY)
		# Must not raise.
		prov.resend_kyc_email(result["platform_name"])

	def test_registration_blocked_without_partner_credentials(self):
		"""With the partner credentials removed, provisioning is refused."""
		frappe.conf.pop("esalink_partner_username", None)
		try:
			with self.assertRaises(frappe.ValidationError):
				prov.register_esalink_company(COMPANY)
		finally:
			frappe.conf["esalink_partner_username"] = "test-partner"
