# Copyright (c) 2026, ALYF GmbH, Dokos SAS and Contributors
# See license.txt

import os
import datetime
import frappe
from frappe.tests import IntegrationTestCase
from etransactions.etransactions.doctype.einvoice.test_data import (
	MINIMUM_INVOICES,
	BASIC_WL_INVOICES,
	BASIC_INVOICES,
	EN16931_INVOICES,
	EXTENDED_INVOICES,
)

IGNORE_TEST_RECORD_DEPENDENCIES = ["Company", "Item", "Currency", "Purchase Order", "Sales Invoice", "Supplier", "Address", "Purchase Order Item"]

class TesteInvoice(IntegrationTestCase):
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
			frappe.get_doc({"doctype": "Company", "company_name": "Test Company", "default_currency": "EUR"}).insert()
		
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
