# Copyright (c) 2026, ALYF GmbH, Dokos SAS and Contributors
# See license.txt

import os
import datetime
import frappe
from etransactions.tests.utils import eTransactionsTestSuite
from etransactions.etransactions.doctype.einvoice.test_data import (
	MINIMUM_INVOICES,
	BASIC_WL_INVOICES,
	BASIC_INVOICES,
	EN16931_INVOICES,
	EXTENDED_INVOICES,
	UBL_INVOICES,
)

IGNORE_TEST_RECORD_DEPENDENCIES = ["Company", "Item", "Currency", "Purchase Order", "Sales Invoice", "Supplier", "Address", "Purchase Order Item"]

class TesteInvoice(eTransactionsTestSuite):
	def setUp(self):
		super().setUp()
		frappe.db.set_default("company", "_Test Company")

	def test_parse_minimum_invoices(self):
		self.run_invoice_tests("0.minimum", MINIMUM_INVOICES)

	def test_parse_basic_wl_invoices(self):
		self.run_invoice_tests("1.basic_wl", BASIC_WL_INVOICES)

	def test_parse_basic_invoices(self):
		self.run_invoice_tests("2.BASIC", BASIC_INVOICES)

	def test_parse_en16931_invoices(self):
		self.run_invoice_tests("3.EN16931", EN16931_INVOICES)

	def test_parse_extended_invoices(self):
		self.run_invoice_tests("4.EXTENDED", EXTENDED_INVOICES)

	def test_parse_ubl_invoices(self):
		self.run_invoice_tests("5.ubl", UBL_INVOICES)

	# ------------------------------------------------------------------
	# UBL-specific tests
	# ------------------------------------------------------------------

	def test_ubl_format_detection(self):
		"""detect_xml_format correctly identifies UBL and FacturX XML."""
		from etransactions.utils.xml import detect_xml_format

		ubl_invoice = (
			b'<?xml version="1.0"?>'
			b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"/>'
		)
		ubl_credit_note = (
			b'<?xml version="1.0"?>'
			b'<CreditNote xmlns="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"/>'
		)
		facturx = (
			b'<?xml version="1.0"?>'
			b'<rsm:CrossIndustryInvoice'
			b' xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"/>'
		)

		self.assertEqual(detect_xml_format(ubl_invoice), "ubl")
		self.assertEqual(detect_xml_format(ubl_credit_note), "ubl")
		self.assertEqual(detect_xml_format(facturx), "facturx")

	def test_ubl_item_parsing(self):
		"""UBL-Invoice-2.1-Example.xml produces 5 items with correct fields."""
		from etransactions.utils.ubl_parser import parse_ubl

		test_path = frappe.get_app_path("etransactions", "tests", "invoices", "5.ubl")
		with open(os.path.join(test_path, "UBL-Invoice-2.1-Example.xml"), "rb") as f:
			xml_bytes = f.read()

		einvoice = frappe.get_doc({"doctype": "eInvoice", "einvoice_type": "Incoming"})
		parse_ubl(xml_bytes, einvoice)  # type: ignore[arg-type]

		self.assertEqual(len(einvoice.items), 5)

		# Item 1 — Labtop computer (qty=1, price=1273)
		item1 = einvoice.items[0]
		self.assertEqual(item1.product_name, "Labtop computer")
		self.assertEqual(item1.seller_product_id, "JB007")
		self.assertEqual(item1.billed_quantity, 1.0)
		self.assertEqual(item1.unit_code, "C62")
		self.assertEqual(item1.net_rate, 1273.0)
		self.assertEqual(item1.total_amount, 1273.0)
		self.assertEqual(item1.tax_rate, 20.0)

		# Item 3 — "Computing for dummies" book (qty=2, price=2.48, line=4.96)
		item3 = einvoice.items[2]
		self.assertEqual(item3.billed_quantity, 2.0)
		self.assertEqual(item3.net_rate, 2.48)
		self.assertEqual(item3.total_amount, 4.96)

		# Item 5 — Network cable (qty=250, price=0.75 each, line=187.5)
		item5 = einvoice.items[4]
		self.assertEqual(item5.product_name, "Network cable")
		self.assertEqual(item5.seller_product_id, "JB011")
		self.assertEqual(item5.billed_quantity, 250.0)
		self.assertEqual(item5.net_rate, 0.75)
		self.assertEqual(item5.total_amount, 187.5)

	def test_ubl_tax_parsing(self):
		"""UBL-Invoice-2.1-Example.xml produces 3 tax rows with correct values."""
		from etransactions.utils.ubl_parser import parse_ubl

		test_path = frappe.get_app_path("etransactions", "tests", "invoices", "5.ubl")
		with open(os.path.join(test_path, "UBL-Invoice-2.1-Example.xml"), "rb") as f:
			xml_bytes = f.read()

		einvoice = frappe.get_doc({"doctype": "eInvoice", "einvoice_type": "Incoming"})
		parse_ubl(xml_bytes, einvoice)  # type: ignore[arg-type]

		self.assertEqual(len(einvoice.taxes), 3)

		# Tax 1: 20% VAT on 1460.5
		t1 = einvoice.taxes[0]
		self.assertEqual(t1.basis_amount, 1460.5)
		self.assertEqual(t1.calculated_amount, 292.1)
		self.assertEqual(t1.rate_applicable_percent, 20.0)

		# Tax 2: 10% VAT on 1
		t2 = einvoice.taxes[1]
		self.assertEqual(t2.basis_amount, 1.0)
		self.assertEqual(t2.calculated_amount, 0.1)
		self.assertEqual(t2.rate_applicable_percent, 10.0)

		# Tax 3: 0% (exempt) on -25
		t3 = einvoice.taxes[2]
		self.assertEqual(t3.basis_amount, -25.0)
		self.assertEqual(t3.calculated_amount, 0.0)
		self.assertEqual(t3.rate_applicable_percent, 0.0)

	def test_ubl_is_return_flag(self):
		"""Invoice sets is_return=0; CreditNote would set is_return=1."""
		from etransactions.utils.ubl_parser import parse_ubl

		test_path = frappe.get_app_path("etransactions", "tests", "invoices", "5.ubl")
		with open(os.path.join(test_path, "UBL-Invoice-2.1-Example.xml"), "rb") as f:
			xml_bytes = f.read()

		einvoice = frappe.get_doc({"doctype": "eInvoice", "einvoice_type": "Incoming"})
		parse_ubl(xml_bytes, einvoice)  # type: ignore[arg-type]
		self.assertEqual(einvoice.is_return, 0)

		# Patch root element to CreditNote to verify the flag flips
		cn_bytes = xml_bytes.replace(
			b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"',
			b'<CreditNote xmlns="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"',
		).replace(b"</Invoice>", b"</CreditNote>").replace(
			b"<cac:InvoiceLine>", b"<cac:CreditNoteLine>"
		).replace(b"</cac:InvoiceLine>", b"</cac:CreditNoteLine>").replace(
			b"<cbc:InvoicedQuantity", b"<cbc:CreditedQuantity"
		).replace(b"</cbc:InvoicedQuantity>", b"</cbc:CreditedQuantity>")

		einvoice_cn = frappe.get_doc({"doctype": "eInvoice", "einvoice_type": "Incoming"})
		parse_ubl(cn_bytes, einvoice_cn)  # type: ignore[arg-type]
		self.assertEqual(einvoice_cn.is_return, 1)

	def run_invoice_tests(self, folder, expected_data):
		test_path = frappe.get_app_path("etransactions", "tests", "invoices", folder)

		for file_name, expected in expected_data.items():
			with self.subTest(file_name=file_name):
				full_path = os.path.abspath(os.path.join(test_path, file_name))

				if not os.path.exists(full_path):
					continue

				with open(full_path, "rb") as f:
					file_content = f.read()

				file_doc = frappe.get_doc({
					"doctype": "File",
					"file_name": file_name,
					"content": file_content,
					"is_private": 1
				})
				file_doc.insert()

				einvoice = frappe.get_doc({
					"doctype": "eInvoice",
					"einvoice_type": "Incoming",
					"einvoice": file_doc.name
				})
				einvoice.insert()

				for field, expected_value in expected.items():
					actual_value = einvoice.get(field)
					if isinstance(actual_value, (datetime.date, datetime.datetime)):
						actual_value = frappe.utils.get_date_str(actual_value)
					self.assertEqual(actual_value, expected_value, f"{field} mismatch for {file_name}")

	def test_generate_supplier_invoice(self):
		# Create a dummy eInvoice
		einvoice = frappe.get_doc({
			"doctype": "eInvoice",
			"einvoice_type": "Incoming",
			"seller_name": "Test Supplier",
			"seller_tax_id": "FR123456789",
			"id": "INV-001",
			"issue_date": "2024-01-01",
			"due_date": "2024-01-31",
			"currency": "EUR",
			"line_total": 100.0,
			"tax_total": 20.0,
			"grand_total": 120.0,
			"items": [
				{
					"product_name": "Test Product",
					"product_description": "Test Description",
					"seller_product_id": "SKU-001",
					"billed_quantity": 1,
					"net_rate": 100.0,
					"total_amount": 100.0
				}
			]
		})
		einvoice.insert()

		# Mock Supplier and Company if they don't exist
		if not frappe.db.exists("Company", "Test Company"):
			frappe.get_doc({"doctype": "Company", "company_name": "Test Company", "country": "France", "default_currency": "EUR"}).insert()
		
		einvoice.company = "Test Company"
		
		if not frappe.db.exists("Supplier", "Test Supplier"):
			frappe.get_doc({"doctype": "Supplier", "supplier_name": "Test Supplier", "tax_id": "FR123456789"}).insert()

		supplier_invoice = einvoice.generate_supplier_invoice()

		self.assertEqual(supplier_invoice.doctype, "Supplier Invoice")
		self.assertEqual(supplier_invoice.supplier, "Test Supplier")
		self.assertEqual(supplier_invoice.bill_no, "INV-001")
		self.assertEqual(supplier_invoice.supplier_grand_total, 120.0)
		self.assertEqual(len(supplier_invoice.items), 1)
		self.assertEqual(supplier_invoice.items[0].supplier_description, "Test Product")
		self.assertEqual(supplier_invoice.einvoice, einvoice.name)

	def test_sales_invoice_to_einvoice(self):
		company = "_Test Company"

		if not frappe.db.exists("Customer", "_Test Customer"):
			frappe.get_doc({
				"doctype": "Customer",
				"customer_name": "_Test Customer",
				"customer_group": "All Customer Groups",
				"territory": "All Territories"
			}).insert()
		
		customer = "_Test Customer"

		item_names = ["_Test Item 1", "_Test Item 2"]
		for item_name in item_names:
			if not frappe.db.exists("Item", item_name):
				frappe.get_doc({
					"doctype": "Item",
					"item_code": item_name,
					"item_group": "All Item Groups",
					"is_stock_item": 0
				}).insert()

		# 4. Create Sales Invoice
		si = frappe.new_doc("Sales Invoice")
		si.company = company
		si.customer = customer
		si.currency = "INR"
		si.posting_date = frappe.utils.today()
		si.etransaction_profile = "EN16931"
		
		si.append("items", {
			"item_code": "_Test Item 1",
			"qty": 2,
			"rate": 50.0,
		})
		si.append("items", {
			"item_code": "_Test Item 2",
			"qty": 1,
			"rate": 100.0,
		})

		si.insert()

		# 5. Check if eInvoice was created automatically (by before_save override)
		einvoice_name = frappe.db.exists("eInvoice", {"sales_invoice": si.name})
		self.assertTrue(einvoice_name, "eInvoice should be created automatically for Sales Invoice")

		einvoice = frappe.get_doc("eInvoice", einvoice_name)

		# 6. Verify eInvoice data
		self.assertEqual(einvoice.einvoice_type, "Outgoing")
		self.assertEqual(einvoice.sales_invoice, si.name)
		self.assertEqual(einvoice.company, company)

		# Check totals
		self.assertEqual(einvoice.grand_total, si.grand_total)
		self.assertEqual(einvoice.line_total, si.total)
		
		# Check items
		self.assertEqual(len(einvoice.items), 2)
		self.assertEqual(einvoice.items[0].product_name, "_Test Item 1")
		self.assertEqual(einvoice.items[0].billed_quantity, 2)
		self.assertEqual(einvoice.items[0].net_rate, 50.0)
		self.assertEqual(einvoice.items[1].product_name, "_Test Item 2")
		self.assertEqual(einvoice.items[1].billed_quantity, 1)
		self.assertEqual(einvoice.items[1].net_rate, 100.0)
