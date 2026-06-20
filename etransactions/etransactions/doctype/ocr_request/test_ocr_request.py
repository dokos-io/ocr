# Copyright (c) 2023, Dokos SAS and Contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from etransactions.utils import parse_currency_symbol

IGNORE_TEST_RECORD_DEPENDENCIES = []


def _supplier_group():
	name = frappe.db.get_value("Supplier Group", {"is_group": 0})
	if name:
		return name
	root = frappe.db.get_value("Supplier Group", {"is_group": 1})
	group = frappe.new_doc("Supplier Group")
	group.supplier_group_name = "_Test OCR Currency Group"
	group.parent_supplier_group = root
	group.is_group = 0
	group.insert(ignore_if_duplicate=True)
	return group.name


def _make_supplier(supplier_name, default_currency=None):
	supplier = frappe.new_doc("Supplier")
	supplier.supplier_name = supplier_name
	supplier.supplier_group = _supplier_group()
	if default_currency:
		supplier.default_currency = default_currency
	supplier.insert(ignore_if_duplicate=True)
	return supplier


class TestParseCurrencySymbol(FrappeTestCase):
	def test_symbols(self):
		self.assertEqual(parse_currency_symbol("$ 54.09"), "USD")
		self.assertEqual(parse_currency_symbol("a 1.190,00 €"), "EUR")
		self.assertEqual(parse_currency_symbol("£12"), "GBP")

	def test_iso_code_wins(self):
		self.assertEqual(parse_currency_symbol("EUR 100,00"), "EUR")
		self.assertEqual(parse_currency_symbol("USD 75.02"), "USD")

	def test_no_currency(self):
		self.assertIsNone(parse_currency_symbol("100,00"))
		self.assertIsNone(parse_currency_symbol(""))
		self.assertIsNone(parse_currency_symbol(None))


class TestOCRRequestCurrency(FrappeTestCase):
	def setUp(self):
		self.suffix = frappe.generate_hash(length=6).upper()
		self.request = frappe.new_doc("OCR Request")

	def tearDown(self):
		frappe.db.rollback()

	def test_supplier_default_currency_is_used(self):
		# A non-company-currency supplier must drive the invoice currency.
		sup = _make_supplier(f"USD Supplier {self.suffix}", default_currency="USD")

		currency = self.request.resolve_currency(sup.name, {"TOTAL": "$ 54.09"})

		self.assertEqual(currency, "USD")

	def test_supplier_default_wins_over_ocr_symbol(self):
		sup = _make_supplier(f"GBP Supplier {self.suffix}", default_currency="GBP")

		# Even if the OCR amount carries a different symbol, the configured supplier
		# currency takes precedence.
		currency = self.request.resolve_currency(sup.name, {"TOTAL": "$ 10.00"})

		self.assertEqual(currency, "GBP")

	def test_falls_back_to_ocr_symbol(self):
		# Supplier without a configured currency: detect it from the OCR amounts.
		sup = _make_supplier(f"No Currency Supplier {self.suffix}")
		frappe.db.set_value("Supplier", sup.name, "default_currency", None)

		currency = self.request.resolve_currency(sup.name, {"TOTAL": "$ 54.09"})

		self.assertEqual(currency, "USD")

	def test_returns_none_when_unresolvable(self):
		# No supplier and no currency signal -> None, so the Supplier Invoice
		# fetch_if_empty fallback fills the company default currency.
		currency = self.request.resolve_currency(None, {"TOTAL": "100,00"})

		self.assertIsNone(currency)
