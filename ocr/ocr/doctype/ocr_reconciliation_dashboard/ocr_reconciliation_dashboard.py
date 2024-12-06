# Copyright (c) 2024, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class OCRReconciliationDashboard(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		company: DF.Link | None
	# end: auto-generated types

	pass

@frappe.whitelist()
def update_ocr_request(ocr_request, data):

	doc = frappe.get_doc("OCR Request", ocr_request)
	doc.update(frappe.parse_json(data))
	doc.save()

	return doc


@frappe.whitelist()
def get_pending_invoices(company, order_by=None):
	return frappe.get_all("OCR Request", filters={"status": ("not in", ["Pending", "Closed"])}, fields=["*"], limit=20, order_by=order_by)


@frappe.whitelist()
def get_matching_documents(ocr_request, document_types):
	doc = frappe.get_doc("OCR Request", ocr_request)

	documents = []
	if "purchase_order" in document_types:
		orders = doc.get_matched_orders()
		for order in orders:
			doc = frappe.get_cached_doc("Purchase Order", order)
			documents.append({
				"doctype": doc.doctype,
				"docname": doc.name,
				"supplier": doc.supplier,
				"transaction_date": doc.transaction_date,
				"net_total": doc.net_total,
				"grand_total": doc.grand_total,
				"per_billed": doc.per_billed,
			})


	return documents


@frappe.whitelist()
def create_purchase_invoice(ocr_request, selected_rows, items):
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice as make_purchase_invoice_from_po
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice as make_purchase_invoice_from_pr

	ocr_request_doc = frappe.get_doc("OCR Request", ocr_request)

	doc = frappe.new_doc("Purchase Invoice")

	for selected_row in frappe.parse_json(selected_rows):
		if selected_row["doctype"] == "Purchase Order":
			make_purchase_invoice_from_po(selected_row["docname"], doc)
		elif selected_row["doctype"] == "Purchase Receipt":
			make_purchase_invoice_from_pr(selected_row["docname"], doc)

	doc.items = []
	for item in frappe.parse_json(items):
		doc.append("items", item)

	for field in ["company", "supplier", "bill_no", "bill_no", "due_date"]:
		doc.update({field: ocr_request_doc.get(field)})

	doc.run_method("set_missing_values")
	doc.run_method("calculate_taxes_and_totals")

	doc.payment_schedule = []

	doc.insert()

	return doc