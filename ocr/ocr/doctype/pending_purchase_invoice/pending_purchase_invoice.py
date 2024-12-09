# Copyright (c) 2024, Dokos SAS and contributors
# For license information, please see license.txt

import re

from pypika.terms import ExistsCriterion

import frappe
from frappe.model.document import Document


class PendingPurchaseInvoice(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from ocr.ocr.doctype.pending_purchase_invoice_item.pending_purchase_invoice_item import PendingPurchaseInvoiceItem

		bill_date: DF.Date | None
		bill_no: DF.Data | None
		company: DF.Link | None
		due_date: DF.Date | None
		file: DF.Link | None
		file_url: DF.SmallText | None
		grand_total: DF.Currency
		items: DF.Table[PendingPurchaseInvoiceItem]
		net_amount: DF.Currency
		status: DF.Literal["Pending", "Completed"]
		supplier: DF.Link | None
		tax_amount: DF.Currency
	# end: auto-generated types
	pass

	def get_matched_orders(self):
		purchase_order_dt = frappe.qb.DocType("Purchase Order")
		purchase_invoice_item_dt = frappe.qb.DocType("Purchase Invoice Item")

		subquery = (
			frappe.qb.from_(purchase_invoice_item_dt)
			.select(purchase_invoice_item_dt.name)
			.where(purchase_invoice_item_dt.docstatus.lt(2))
			.where(purchase_invoice_item_dt.purchase_order == purchase_order_dt.name)
		)

		query = (
			frappe.qb.from_(purchase_order_dt)
			.select(purchase_order_dt.name, purchase_order_dt.net_total, purchase_order_dt.order_confirmation_no, purchase_order_dt.company)
			.where((purchase_order_dt.docstatus == 1) & (purchase_order_dt.per_billed.lt(100)) & (purchase_order_dt.status.notin(["Closed", "Completed"])))
			.where(ExistsCriterion(subquery).negate())
		)

		if self.supplier:
			query = query.where(purchase_order_dt.supplier == self.supplier)

		open_orders = query.run(as_dict=True)

		matched_orders = set()
		if self.get_creation_mode() == "Get items from purchase orders recognized by the OCR":
			for child in self.items:
				for open_order in open_orders:
					if re.search(r"(?<![\w\d])" + re.escape(open_order.name) + r"(?![\w\d])", child.get("expense_row") or "", re.IGNORECASE):
						matched_orders.add(open_order.name)
					elif re.search(r"(?<![\w\d])" + re.escape(open_order.order_confirmation_no or "") + r"(?![\w\d])", child.get("expense_row") or "", re.IGNORECASE):
						matched_orders.add(open_order.name)
		elif open_orders:
			if closest_order := min(open_orders, key=lambda x:abs(x.net_total - self.net_total)):
				matched_orders.add(closest_order.name)

		return matched_orders

	def get_creation_mode(self):
		if self.get("pi_creation_mode"):
			return self.pi_creation_mode

		pi_creation_mode = None
		if self.supplier:
			pi_creation_mode = frappe.db.get_value("Supplier", self.supplier, "ocr_pi_creation_mode")

		if not pi_creation_mode:
			pi_creation_mode = frappe.db.get_single_value("OCR Settings", "pi_creation_mode")

		self.pi_creation_mode = pi_creation_mode
		return self.pi_creation_mode


@frappe.whitelist()
def get_matching_documents(purchase_invoice, document_types):
	doc = frappe.get_doc("Pending Purchase Invoice", purchase_invoice)

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