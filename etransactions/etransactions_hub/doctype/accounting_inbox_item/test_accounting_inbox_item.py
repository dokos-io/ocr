# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import change_settings

from etransactions.tests.utils import eTransactionsTestSuite, minimal_pdf_content

IGNORE_TEST_RECORD_DEPENDENCIES = []


class TestAccountingInboxItem(eTransactionsTestSuite):
	def make_item(self, **kwargs):
		item = frappe.new_doc("Accounting Inbox Item")
		item.update(kwargs)
		item.insert()
		return item

	def attach_file(self, doctype: str, name: str, file_name: str | None = None) -> str:
		file = frappe.new_doc("File")
		file.update(
			{
				"file_name": file_name or f"invoice-{frappe.generate_hash(length=6)}.pdf",
				"attached_to_doctype": doctype,
				"attached_to_name": name,
				"is_private": 1,
				"content": minimal_pdf_content(),
			}
		)
		file.insert()
		return file.name

	def test_defaults_for_email_item(self):
		item = self.make_item(sender="supplier@example.com", subject="Invoice June")
		self.assertEqual(item.source, "Email")
		self.assertEqual(item.status, "To Triage")
		self.assertEqual(item.title, "Invoice June")

	def test_defaults_for_manual_item(self):
		item = self.make_item(title="Scanned receipt")
		self.assertEqual(item.source, "Manual Upload")
		self.assertEqual(item.status, "To Triage")

	def test_create_request(self):
		item = self.make_item(sender="supplier@example.com", subject="Question about invoice")
		request_name = item.create_request(request_type="Question")

		request = frappe.get_doc("Accounting Request", request_name)
		self.assertEqual(request.inbox_item, item.name)
		self.assertEqual(request.request_type, "Question")
		self.assertEqual(request.subject, "Question about invoice")

		item.reload()
		self.assertEqual(item.created_request, request_name)
		self.assertEqual(item.status, "In Progress")

	def test_create_supplier_invoice_requires_file(self):
		item = self.make_item(title="Empty item")
		self.assertRaises(frappe.ValidationError, item.create_supplier_invoice)

	@change_settings(
		"eTransactions Settings",
		{"ocr_service": "Amazon Textract", "aws_textract_key": "", "aws_textract_secret": ""},
	)
	def test_create_supplier_invoice(self):
		item = self.make_item(sender="supplier@example.com", subject="Invoice with PDF")
		self.attach_file(item.doctype, item.name)

		basket_name = item.create_supplier_invoice()

		self.assertTrue(frappe.db.exists("Supplier Invoices Basket", basket_name))

		# the file was copied to the basket, the original stays on the item
		self.assertTrue(
			frappe.db.exists(
				"File", {"attached_to_doctype": "Supplier Invoices Basket", "attached_to_name": basket_name}
			)
		)
		self.assertTrue(
			frappe.db.exists(
				"File", {"attached_to_doctype": item.doctype, "attached_to_name": item.name}
			)
		)

		item.reload()
		self.assertEqual(item.created_invoices_basket, basket_name)
		self.assertEqual(item.status, "Processed")

	def test_archive(self):
		item = self.make_item(title="Newsletter")
		item.archive()
		self.assertEqual(
			frappe.db.get_value("Accounting Inbox Item", item.name, "status"), "Archived"
		)
