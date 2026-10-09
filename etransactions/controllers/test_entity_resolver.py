# Copyright (c) 2026, Dokos SAS and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from etransactions.controllers.entity_resolver import InvoiceEntityResolverMixin


def _supplier_group():
	"""Return an existing leaf Supplier Group, creating one under the root if needed."""
	name = frappe.db.get_value("Supplier Group", {"is_group": 0})
	if name:
		return name
	root = frappe.db.get_value("Supplier Group", {"is_group": 1})
	group = frappe.new_doc("Supplier Group")
	group.supplier_group_name = "_Test Resolver Group"
	group.parent_supplier_group = root
	group.is_group = 0
	group.insert(ignore_if_duplicate=True)
	return group.name


def _make_supplier(supplier_name, tax_id=None):
	supplier = frappe.new_doc("Supplier")
	supplier.supplier_name = supplier_name
	supplier.supplier_group = _supplier_group()
	if tax_id:
		supplier.tax_id = tax_id
	supplier.insert(ignore_if_duplicate=True)
	return supplier


class TestEntityResolver(FrappeTestCase):
	def setUp(self):
		self.resolver = InvoiceEntityResolverMixin()
		self.suffix = frappe.generate_hash(length=6).upper()

	def tearDown(self):
		frappe.db.rollback()

	def test_unique_tax_id_matches_high(self):
		tax_id = f"FR{self.suffix}001"
		sup = _make_supplier(f"Unique TaxId {self.suffix}", tax_id=tax_id)

		result = self.resolver.resolve_supplier(seller_name="Whatever", tax_id=tax_id)

		self.assertEqual(result, sup.name)
		self.assertEqual(self.resolver._match_confidence, "high")

	def test_unique_tax_id_matches_despite_formatting(self):
		sup = _make_supplier(f"Spaced TaxId {self.suffix}", tax_id=f"FR{self.suffix}002")

		result = self.resolver.resolve_supplier(
			seller_name="Whatever", tax_id=f"FR {self.suffix} 002"
		)

		self.assertEqual(result, sup.name)
		self.assertEqual(self.resolver._match_confidence, "high")

	def test_ambiguous_tax_id_does_not_pick_arbitrarily(self):
		# Two suppliers sharing the same tax_id (the bug's pollution scenario).
		shared = f"FR{self.suffix}003"
		_make_supplier(f"Ambiguous A {self.suffix}", tax_id=shared)
		_make_supplier(f"Ambiguous B {self.suffix}", tax_id=shared)

		# With no other signal, an ambiguous tax_id must NOT resolve to an arbitrary
		# supplier and must NOT be reported as high confidence.
		result = self.resolver.resolve_supplier(seller_name=None, tax_id=shared)

		self.assertEqual(result, "")
		self.assertEqual(self.resolver._match_confidence, "low")

	def test_ambiguous_tax_id_falls_through_to_name(self):
		shared = f"FR{self.suffix}004"
		sup_a = _make_supplier(f"Real Seller {self.suffix}", tax_id=shared)
		_make_supplier(f"Other Seller {self.suffix}", tax_id=shared)

		# Ambiguous tax_id is skipped; the exact name match wins instead of an arbitrary
		# tax_id pick.
		result = self.resolver.resolve_supplier(
			seller_name=f"Real Seller {self.suffix}", tax_id=shared
		)

		self.assertEqual(result, sup_a.name)

	def test_buyer_vat_is_never_used_as_supplier_key(self):
		# Simulate the buyer's own VAT having leaked onto a supplier master.
		buyer_vat = f"FR{self.suffix}005"
		company = frappe.get_all("Company", limit=1, pluck="name")[0]
		original = frappe.db.get_value("Company", company, "tax_id")
		frappe.db.set_value("Company", company, "tax_id", buyer_vat)
		try:
			_make_supplier(f"Polluted Supplier {self.suffix}", tax_id=buyer_vat)

			result = self.resolver.resolve_supplier(seller_name=None, tax_id=buyer_vat)

			self.assertEqual(result, "")
		finally:
			frappe.db.set_value("Company", company, "tax_id", original)

	def test_exact_name_matches_high(self):
		name = f"Exact Name Co {self.suffix}"
		sup = _make_supplier(name)

		result = self.resolver.resolve_supplier(seller_name=name)

		self.assertEqual(result, sup.name)
		self.assertEqual(self.resolver._match_confidence, "high")

	def test_no_match_returns_empty_low(self):
		result = self.resolver.resolve_supplier(
			seller_name=f"Totally Unknown Vendor {self.suffix}"
		)

		self.assertEqual(result, "")
		self.assertEqual(self.resolver._match_confidence, "low")

	# --- Vendor name aliases -------------------------------------------------

	def _make_alias(self, supplier, vendor_name):
		# Inserted straight into the table: the controller now refuses ambiguous rows, but
		# sites upgraded from earlier versions still hold them.
		alias = frappe.new_doc("eTransactions Supplier Name Alias")
		alias.supplier = supplier
		alias.vendor_name = vendor_name
		alias.db_insert()
		return alias

	def test_unique_alias_matches_high(self):
		sup = _make_supplier(f"Aliased Seller {self.suffix}")
		vendor_name = f"ALIASED SELLER SARL {self.suffix}"
		self._make_alias(sup.name, vendor_name)

		result = self.resolver.resolve_supplier(seller_name=vendor_name)

		self.assertEqual(result, sup.name)
		self.assertEqual(self.resolver._match_confidence, "high")

	def test_alias_matches_across_ocr_line_breaks(self):
		sup = _make_supplier(f"Wrapped Seller {self.suffix}")
		self._make_alias(sup.name, f"Wrapped Vendor Block {self.suffix}")

		result = self.resolver.resolve_supplier(
			seller_name=f"Wrapped Vendor\n Block  {self.suffix}"
		)

		self.assertEqual(result, sup.name)

	def test_ambiguous_alias_does_not_pick_arbitrarily(self):
		"""The reported symptom: one OCR'd name claimed by several suppliers."""
		shared_vendor_name = f"DOKOS SAS {self.suffix}"
		_make_supplier(f"Alias Claimant A {self.suffix}")
		_make_supplier(f"Alias Claimant B {self.suffix}")
		self._make_alias(f"Alias Claimant A {self.suffix}", shared_vendor_name)
		self._make_alias(f"Alias Claimant B {self.suffix}", shared_vendor_name)

		result = self.resolver.resolve_supplier(seller_name=shared_vendor_name)

		self.assertEqual(result, "")
		self.assertEqual(self.resolver._match_confidence, "low")

	def test_alias_on_own_company_name_is_rejected(self):
		company = frappe.get_all("Company", limit=1, pluck="name")[0]
		sup = _make_supplier(f"Wrongly Learned {self.suffix}")

		alias = frappe.new_doc("eTransactions Supplier Name Alias")
		alias.supplier = sup.name
		alias.vendor_name = f"{company} SAS"

		self.assertRaises(frappe.ValidationError, alias.insert)

	def test_alias_cannot_be_claimed_by_a_second_supplier(self):
		vendor_name = f"Contested Vendor {self.suffix}"
		first = _make_supplier(f"First Claimant {self.suffix}")
		second = _make_supplier(f"Second Claimant {self.suffix}")
		self._make_alias(first.name, vendor_name)

		alias = frappe.new_doc("eTransactions Supplier Name Alias")
		alias.supplier = second.name
		alias.vendor_name = vendor_name

		self.assertRaises(frappe.ValidationError, alias.insert)


class TestBuyerCompanyMatching(FrappeTestCase):
	"""How an OCR-read buyer name or address finds one of our companies.

	Names carry a random suffix: the test site has other companies, and the match must stay unique.
	"""

	def setUp(self):
		self.suffix = frappe.generate_hash(length=6).upper()
		self.menuiserie = self._company(f"Menuiserie Élégante {self.suffix}", f"ME{self.suffix}")

	def tearDown(self):
		frappe.db.rollback()

	def _company(self, name, abbr):
		# Only the row is needed: a full insert would also build a chart of accounts.
		frappe.get_doc({
			"doctype": "Company",
			"name": name,
			"company_name": name,
			"abbr": abbr,
			"country": "France",
			"default_currency": "EUR",
		}).db_insert()
		return name

	def _address(self, company, line1, pincode, title=None):
		frappe.get_doc({
			"doctype": "Address",
			"address_title": title or company,
			"address_type": "Billing",
			"address_line1": line1,
			"city": "Ville",
			"pincode": pincode,
			"country": "France",
			"links": [{"link_doctype": "Company", "link_name": company}],
		}).insert()

	def _resolve(self, name=None, address=None):
		from etransactions.controllers.entity_resolver import resolve_buyer_company

		return resolve_buyer_company(name, address=address, use_default=False)

	def test_company_name_inside_a_multiline_address(self):
		address = f"MENUISERIE ELEGANTE {self.suffix}\n8 rue des Tilleuls\n99456 VILLE"
		self.assertEqual(self._resolve(address=address), self.menuiserie)

	def test_abbreviation_around_a_legal_form(self):
		self.assertEqual(self._resolve(f"SARL ME{self.suffix}"), self.menuiserie)

	def test_address_title(self):
		self._address(self.menuiserie, "8 rue des Tilleuls", "99456", title=f"MEL{self.suffix}")
		self.assertEqual(self._resolve(f"MEL{self.suffix}"), self.menuiserie)

	def test_learned_alias(self):
		frappe.get_doc({
			"doctype": "eTransactions Company Name Alias",
			"company": self.menuiserie,
			"receiver_name": f"Menuis du Plateau {self.suffix}",
		}).insert()
		self.assertEqual(self._resolve(f"MENUIS DU PLATEAU {self.suffix}"), self.menuiserie)

	def test_misspelled_name(self):
		self.assertEqual(self._resolve(f"MENUISERIE ELEGANTTE {self.suffix} SAS"), self.menuiserie)

	def test_unique_company_address(self):
		self._address(self.menuiserie, "12 impasse des Glycines", "99123")
		address = "SAS UNKNOWN NAME\n12 IMPASSE DES GLYCINES\n99123 VILLE"
		self.assertEqual(self._resolve("SAS UNKNOWN NAME", address), self.menuiserie)

	def test_shared_address_matches_no_company(self):
		other = self._company(f"Atelier Martin {self.suffix}", f"AMA{self.suffix}")
		for company in (self.menuiserie, other):
			self._address(company, "12 impasse des Glycines", "99123")
		self.assertIsNone(self._resolve("SAS UNKNOWN NAME", "12 IMPASSE DES GLYCINES\n99123 VILLE"))

	def test_a_shared_word_is_not_enough(self):
		"""Another joiner is not our Menuiserie."""
		self.assertIsNone(self._resolve(f"SAS MENUISERIE DU PARC {self.suffix}"))

	def test_ocr_buyer_read_as_name_and_address(self):
		"""Textract often leaves the receiver empty and reads the buyer block as NAME/ADDRESS."""
		from etransactions.controllers.entity_resolver import resolve_ocr_buyer_company

		analysis = {"NAME": f"MENUISERIE ELEGANTE {self.suffix}", "VENDOR_NAME": "Wood Supplier"}
		self.assertEqual(resolve_ocr_buyer_company(analysis), self.menuiserie)

		# NAME/ADDRESS may be the vendor's when the vendor is one of our companies
		analysis["VENDOR_NAME"] = self.menuiserie
		self.assertIsNone(resolve_ocr_buyer_company(analysis))
