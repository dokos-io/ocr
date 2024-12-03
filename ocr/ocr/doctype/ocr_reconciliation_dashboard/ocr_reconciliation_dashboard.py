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
		print("orders", orders)
		for order in orders:
			documents.append(frappe.get_cached_doc("Purchase Order", order))


	return documents
