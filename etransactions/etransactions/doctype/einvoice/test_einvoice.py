# Copyright (c) 2026, ALYF GmbH, Dokos SAS and Contributors
# See license.txt

from os.path import abspath, join
import frappe
from frappe.tests import IntegrationTestCase

IGNORE_TEST_RECORD_DEPENDENCIES = ["Company", "Item", "Currency", "Purchase Order", "Sales Invoice", "Supplier", "Address", "Purchase Order Item"]

class TesteInvoice(IntegrationTestCase):
	def test_parse_minimum_invoice_pdf(self):
		test_path = frappe.get_app_path("etransactions", "tests", "invoices")
		full_path = abspath(join(test_path, "2.BASIC", "Facture_F20220023-LE_FOURNISSEUR-POUR-LE_CLIENT_BASIC.pdf"))

		with open(full_path, "rb") as f:
			file_content = f.read()

		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": "Facture_F20220023-LE_FOURNISSEUR-POUR-LE_CLIENT_BASIC.pdf",
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

		# Basic assertions to ensure parsing worked
		self.assertEqual(einvoice.id, "F20220023")
		self.assertEqual(einvoice.seller_name, "LE FOURNISSEUR")
		self.assertEqual(einvoice.buyer_name, "LE CLIENT")
		self.assertEqual(einvoice.currency, "EUR")
		# self.assertEqual(len(einvoice.items), 1)
		# self.assertEqual(einvoice.grand_total, 120.0)
