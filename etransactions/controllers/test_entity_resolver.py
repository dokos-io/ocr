# Copyright (c) 2026, Dokos SAS and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from etransactions.controllers.entity_resolver import InvoiceEntityResolverMixin


def _make_supplier(supplier_name, tax_id=None):
	supplier = frappe.new_doc("Supplier")
	supplier.supplier_name = supplier_name
	supplier.supplier_group = "Services"
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
