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
