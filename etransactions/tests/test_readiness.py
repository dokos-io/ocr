# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from erpnext import get_default_company

from etransactions.tests.utils import eTransactionsTestSuite
from etransactions.plateforme_agreee.readiness import (
	evaluate_einvoice_readiness,
	evaluate_party_readiness,
)
from etransactions.utils import EInvoiceProfile


class TestPartyReadiness(eTransactionsTestSuite):
	def _customer_group(self):
		return frappe.get_all("Customer Group", filters={"is_group": 0}, pluck="name")[0]

	def _make_customer(self, suffix, **updates):
		name = f"_Test Readiness {suffix}"
		if frappe.db.exists("Customer", name):
			frappe.delete_doc("Customer", name, ignore_permissions=True, force=True)
		frappe.get_doc({
			"doctype": "Customer",
			"customer_name": name,
			"customer_group": self._customer_group(),
			"territory": "All Territories",
		}).insert(ignore_permissions=True)
		if updates:
			frappe.db.set_value("Customer", name, updates)
		self.addCleanup(self._delete_customer, name)
		return name

	def _delete_customer(self, name):
		if frappe.db.exists("Customer", name):
			frappe.delete_doc("Customer", name, ignore_permissions=True, force=True)

	def _make_address(self, customer, suffix, **fields):
		addr = frappe.get_doc({
			"doctype": "Address",
			"address_title": f"_Test Readiness Addr {suffix}",
			"address_type": "Billing",
			"is_primary_address": 1,
			"links": [{"link_doctype": "Customer", "link_name": customer}],
			**fields,
		}).insert(ignore_permissions=True)
		self.addCleanup(self._delete_address, addr.name)
		return addr.name

	def _delete_address(self, name):
		if frappe.db.exists("Address", name):
			frappe.delete_doc("Address", name, ignore_permissions=True, force=True)

	def test_blank_customer_flags_blocking_identity(self):
		customer = self._make_customer("blank")
		findings = evaluate_party_readiness("Customer", customer)
		by_key = {f["key"]: f for f in findings}

		# Identity + address are blocking errors when absent.
		for key in ("siren", "tax_id", "address"):
			self.assertIn(key, by_key)
			self.assertEqual(by_key[key]["severity"], "error")

	def test_siret_finding_points_at_resolved_address(self):
		customer = self._make_customer("with-addr", siren_number="853322915", tax_id="FR12853322915")
		address = self._make_address(
			customer, "with-addr",
			address_line1="1 rue de Test", city="Paris", pincode="75001", country="France",
		)  # no siret_number

		findings = evaluate_party_readiness("Customer", customer)
		by_key = {f["key"]: f for f in findings}

		self.assertNotIn("siren", by_key)
		self.assertNotIn("tax_id", by_key)
		self.assertNotIn("address", by_key)
		# SIRET missing on the resolved billing address, fix points at that Address.
		self.assertIn("siret", by_key)
		self.assertEqual(by_key["siret"]["fix_doctype"], "Address")
		self.assertEqual(by_key["siret"]["fix_name"], address)

	def test_invalid_siren_warns_non_blocking(self):
		# Present but Luhn-invalid SIREN: presence check passes, validity warns.
		customer = self._make_customer("bad-siren", siren_number="127741217")
		by_key = {f["key"]: f for f in evaluate_party_readiness("Customer", customer)}

		self.assertNotIn("siren", by_key)  # presence satisfied
		self.assertIn("siren_valid", by_key)
		self.assertEqual(by_key["siren_valid"]["severity"], "warning")

	def test_mismatched_vat_warns_non_blocking(self):
		# Valid SIREN, but the VAT embeds a different SIREN.
		customer = self._make_customer(
			"vat-mismatch", siren_number="853322915", tax_id="FR00111111111"
		)
		by_key = {f["key"]: f for f in evaluate_party_readiness("Customer", customer)}

		self.assertNotIn("siren_valid", by_key)  # SIREN itself is valid
		self.assertIn("siren_vat_match", by_key)
		self.assertEqual(by_key["siren_vat_match"]["severity"], "warning")

	def test_peppol_display_number_does_not_warn(self):
		# Sandbox convention: a Peppol customer stores a non-SIREN display number.
		customer = self._make_customer(
			"peppol", siren_number="000000001", directory_type="peppol"
		)
		by_key = {f["key"]: f for f in evaluate_party_readiness("Customer", customer)}

		self.assertNotIn("siren_valid", by_key)
		self.assertNotIn("siren_vat_match", by_key)

	def test_complete_customer_has_no_blocking_findings(self):
		customer = self._make_customer("ready", siren_number="853322915", tax_id="FR12853322915")
		self._make_address(
			customer, "ready",
			siret_number="85332291500012",
			address_line1="1 rue de Test", city="Paris", pincode="75001", country="France",
		)
		# A primary contact is required (blocking) — create and link one.
		contact = frappe.get_doc({
			"doctype": "Contact",
			"first_name": "_Test Readiness Contact",
			"email_ids": [{"email_id": "ready@example.com", "is_primary": 1}],
			"links": [{"link_doctype": "Customer", "link_name": customer}],
		}).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("Contact", contact.name, force=True, ignore_permissions=True))
		frappe.db.set_value("Customer", customer, {
			"customer_primary_contact": contact.name,
			"email_id": "ready@example.com",
		})

		findings = evaluate_party_readiness("Customer", customer)
		blocking = [f for f in findings if f["severity"] == "error"]
		self.assertEqual(blocking, [])


class TestInvoiceReadiness(eTransactionsTestSuite):
	def test_skips_when_no_profile(self):
		doc = frappe.new_doc("Sales Invoice")
		doc.company = get_default_company()
		self.assertEqual(evaluate_einvoice_readiness(doc), [])

	def test_flags_missing_seller_address(self):
		doc = frappe.new_doc("Sales Invoice")
		doc.company = get_default_company()
		doc.etransaction_profile = EInvoiceProfile.EN16931.value
		# no company_address set
		keys = {f.key for f in evaluate_einvoice_readiness(doc)}
		self.assertIn("seller_address", keys)

	def test_check_invoice_readiness_merges_party(self):
		import json

		from etransactions.plateforme_agreee.readiness import check_invoice_readiness

		customer = frappe.get_all("Customer", limit=1, pluck="name")
		if not customer:
			self.skipTest("no customer available")
		si = {
			"doctype": "Sales Invoice",
			"company": get_default_company(),
			"customer": customer[0],
			"etransaction_profile": EInvoiceProfile.EN16931.value,
		}
		findings = check_invoice_readiness(json.dumps(si))
		# Party-derived findings carry a Customer fix target.
		party = [f for f in findings if f.get("fix_doctype") == "Customer"]
		self.assertTrue(party, "expected at least one Customer-targeted finding")
