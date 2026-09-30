# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from erpnext import get_default_company
from frappe.tests import UnitTestCase

from etransactions.plateforme_agreee.readiness import (
	_platform_finding,
	_split_reasons,
	evaluate_einvoice_readiness,
	evaluate_party_readiness,
)
from etransactions.tests.utils import eTransactionsTestSuite
from etransactions.utils import EInvoiceProfile


class TestPartyReadiness(eTransactionsTestSuite):
	def _customer_group(self):
		return frappe.get_all("Customer Group", filters={"is_group": 0}, pluck="name")[0]

	def _make_customer(self, suffix, **updates):
		name = f"_Test Readiness {suffix}"
		if frappe.db.exists("Customer", name):
			frappe.delete_doc("Customer", name, ignore_permissions=True, force=True)
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_group": self._customer_group(),
				"territory": "All Territories",
			}
		).insert(ignore_permissions=True)
		if updates:
			frappe.db.set_value("Customer", name, updates)
		self.addCleanup(self._delete_customer, name)
		return name

	def _delete_customer(self, name):
		if frappe.db.exists("Customer", name):
			frappe.delete_doc("Customer", name, ignore_permissions=True, force=True)

	def _make_address(self, customer, suffix, **fields):
		addr = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"_Test Readiness Addr {suffix}",
				"address_type": "Billing",
				"is_primary_address": 1,
				"links": [{"link_doctype": "Customer", "link_name": customer}],
				**fields,
			}
		).insert(ignore_permissions=True)
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
			customer,
			"with-addr",
			address_line1="1 rue de Test",
			city="Paris",
			pincode="75001",
			country="France",
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
		customer = self._make_customer("vat-mismatch", siren_number="853322915", tax_id="FR00111111111")
		by_key = {f["key"]: f for f in evaluate_party_readiness("Customer", customer)}

		self.assertNotIn("siren_valid", by_key)  # SIREN itself is valid
		self.assertIn("siren_vat_match", by_key)
		self.assertEqual(by_key["siren_vat_match"]["severity"], "warning")

	def test_peppol_display_number_does_not_warn(self):
		# Sandbox convention: a Peppol customer stores a non-SIREN display number.
		customer = self._make_customer("peppol", siren_number="000000001", directory_type="peppol")
		by_key = {f["key"]: f for f in evaluate_party_readiness("Customer", customer)}

		self.assertNotIn("siren_valid", by_key)
		self.assertNotIn("siren_vat_match", by_key)

	def test_complete_customer_has_no_blocking_findings(self):
		customer = self._make_customer("ready", siren_number="853322915", tax_id="FR12853322915")
		self._make_address(
			customer,
			"ready",
			siret_number="85332291500012",
			address_line1="1 rue de Test",
			city="Paris",
			pincode="75001",
			country="France",
		)
		# A primary contact is required (blocking) — create and link one.
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "_Test Readiness Contact",
				"email_ids": [{"email_id": "ready@example.com", "is_primary": 1}],
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("Contact", contact.name, force=True, ignore_permissions=True)
		)
		frappe.db.set_value(
			"Customer",
			customer,
			{
				"customer_primary_contact": contact.name,
				"email_id": "ready@example.com",
			},
		)

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


class TestPlatformErrorMapping(UnitTestCase):
	"""Pure-logic mapping of platform / schematron messages to fixable findings."""

	def test_split_reasons(self):
		self.assertEqual(_split_reasons("a; b\nc"), ["a", "b", "c"])
		self.assertEqual(_split_reasons(None), [])
		self.assertEqual(_split_reasons("x; x"), ["x"])  # de-duplicated

	def test_mapping_to_fix_targets(self):
		cases = {
			"receiver address does not exist in directory": "Customer",
			"BR-FR-23/BT-34 l'adresse électronique (ram:URIID) invalide": "Company",
			"BR-FR-05/BT-22 mention pénalités de retard absente": "Company",
			"BR-FR-08/BT-23 business process invalide": "eTransactions Settings",
		}
		for message, expected_dt in cases.items():
			finding = _platform_finding("k", message, "error", company="DKY", customer="ACME")
			self.assertEqual(finding.fix_doctype, expected_dt, message)

	def test_unmapped_message_has_no_fix(self):
		finding = _platform_finding("k", "some opaque platform error", "error", "DKY", "ACME")
		self.assertIsNone(finding.fix_doctype)
		self.assertEqual(finding.label, "some opaque platform error")


class TestProfileKillSwitch(UnitTestCase):
	"""A missing eTransaction Profile on a B2B/B2G invoice must surface as a
	finding instead of silently disabling the whole pipeline."""

	def _findings(self, cls_name, profile_choice=True):
		from types import SimpleNamespace
		from unittest.mock import patch

		from etransactions.plateforme_agreee.classification import TransactionClass
		from etransactions.plateforme_agreee.readiness import evaluate_einvoice_readiness

		doc = SimpleNamespace(
			doctype="Sales Invoice",
			get=lambda k, d=None: {
				"etransaction_profile": None,
				"company": "_Test Company",
				"customer": "_Test Customer",
				"customer_address": None,
			}.get(k, d),
		)
		with (
			patch(
				"etransactions.plateforme_agreee.classification.classify_transaction",
				return_value=TransactionClass(cls_name),
			),
			patch(
				"etransactions.plateforme_agreee.readiness.is_feature_enabled",
				side_effect=lambda feature: profile_choice and feature == "profile_choice",
			),
		):
			return evaluate_einvoice_readiness(doc)

	def test_without_profile_choice_points_to_settings(self):
		"""The profile field is hidden without profile choice: fix the default in Settings."""
		findings = self._findings("B2B", profile_choice=False)
		self.assertEqual([f.key for f in findings], ["missing_profile"])
		self.assertIsNone(findings[0].fix_field)
		self.assertEqual(findings[0].fix_doctype, "eTransactions Settings")

	def test_b2b_without_profile_warns(self):
		findings = self._findings("B2B")
		self.assertEqual([f.key for f in findings], ["missing_profile"])
		self.assertEqual(findings[0].severity, "warning")
		self.assertEqual(findings[0].fix_field, "etransaction_profile")

	def test_b2c_without_profile_stays_silent(self):
		self.assertEqual(self._findings("B2C"), [])


class TestPlatformFrameworkSupport(UnitTestCase):
	"""Esalink handles only B2B and B2G billing frameworks, and exposes no
	e-reporting either — a B2Bi/B2C sale would be neither invoiced nor declared,
	so the invoice form must say so."""

	def _findings(self, cls_name, platform_type):
		from types import SimpleNamespace
		from unittest.mock import patch

		from etransactions.plateforme_agreee.classification import TransactionClass
		from etransactions.plateforme_agreee.readiness import _platform_framework_findings

		doc = SimpleNamespace(
			get=lambda k, d=None: {
				"company": "_Test Company",
				"customer": "_Test Customer",
				"customer_address": None,
			}.get(k, d),
		)
		with (
			patch(
				"etransactions.plateforme_agreee.session.get_platform_for_company",
				return_value=SimpleNamespace(name="_Test Platform", platform_type=platform_type),
			),
			patch(
				"etransactions.plateforme_agreee.classification.classify_transaction",
				return_value=TransactionClass(cls_name),
			),
		):
			return _platform_framework_findings(doc)

	def test_esalink_warns_on_unsupported_framework(self):
		findings = self._findings("B2Bi", "Esalink")
		self.assertEqual([f.key for f in findings], ["platform_framework_unsupported"])
		self.assertEqual(findings[0].severity, "warning")
		self.assertIn("B2B, B2G", findings[0].detail)

	def test_esalink_stays_silent_on_supported_frameworks(self):
		self.assertEqual(self._findings("B2B", "Esalink"), [])
		self.assertEqual(self._findings("B2G", "Esalink"), [])

	def test_unrestricted_platform_stays_silent(self):
		self.assertEqual(self._findings("B2Bi", "SuperPDP"), [])

	def test_unknown_platform_type_is_never_gated(self):
		from etransactions.plateforme_agreee.session import platform_supports_processing_rule

		self.assertTrue(platform_supports_processing_rule("BrandNewPDP", "B2Bi"))
		self.assertTrue(platform_supports_processing_rule("Esalink", "B2G"))
		self.assertFalse(platform_supports_processing_rule("Esalink", "OutOfScope"))


class TestCompanyChecks(UnitTestCase):
	"""Seller-side readiness specs (company widget)."""

	def test_specs_tolerate_empty_row(self):
		from etransactions.plateforme_agreee.readiness import company_check_specs

		for spec in company_check_specs():
			spec.passes({})  # must not crash

	def test_electronic_address_paths(self):
		from etransactions.plateforme_agreee.readiness import _company_electronic_address_ok

		self.assertFalse(_company_electronic_address_ok({}))
		self.assertTrue(_company_electronic_address_ok({"email": "billing@x.fr"}))
		self.assertTrue(
			_company_electronic_address_ok(
				{
					"etransactions_electronic_address_scheme": "0002",
					"etransactions_electronic_address": "824710776",
				}
			)
		)
