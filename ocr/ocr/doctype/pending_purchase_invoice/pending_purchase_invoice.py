# Copyright (c) 2024, Dokos SAS and contributors
# For license information, please see license.txt

import re
import difflib
from frappe.model.document import Document
from pypika.terms import ExistsCriterion

from frappe.model.meta import data_fieldtypes, default_fields, child_table_fields

from frappe.query_builder import Order
from frappe import _
from frappe.utils import flt, nowdate
from erpnext.accounts.party import get_due_date

import frappe
from frappe.utils import sbool


EXCLUDED_FIELDS = [*default_fields, *child_table_fields, "status"]

class PendingPurchaseInvoice(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from ocr.ocr.doctype.pending_purchase_invoice_item.pending_purchase_invoice_item import PendingPurchaseInvoiceItem

		bill_date: DF.Date | None
		bill_no: DF.Data | None
		company: DF.Link
		currency: DF.Link
		due_date: DF.Date | None
		file: DF.Link | None
		file_url: DF.SmallText | None
		grand_total: DF.Currency
		items: DF.Table[PendingPurchaseInvoiceItem]
		name: DF.Int | None
		net_total: DF.Currency
		ocr_basket: DF.Link | None
		ocr_request: DF.Link | None
		posting_date: DF.Date
		status: DF.Literal["Pending", "In Progress", "Completed", "Closed"]
		supplier: DF.Link
		supplier_grand_total: DF.Currency
		supplier_net_amount: DF.Currency
		supplier_tax_amount: DF.Currency
		tax_category: DF.Link | None
		tax_id: DF.Data | None
		tax_total: DF.Currency
		taxes_and_charges: DF.Link | None
		title: DF.Data | None
		vendor_address: DF.SmallText | None
	# end: auto-generated types

	def validate(self):
		self.get_supplier()

		if self.supplier:
			self.title = f"{self.supplier} : {self.bill_no}"[:140] if self.bill_no else f"{self.supplier}"[:140]
		else:
			self.title = _("Missing Supplier")
		self.calculate_due_date()

		if not self.items:
			self.append_matched_orders()

	def on_update(self):
		self.calculate_totals()

	def get_supplier(self):
		if self.supplier:
			return

		# 1. Get from previous invoices with same address
		if self.vendor_address:
			invoices = frappe.get_all("Pending Purchase Invoice", filters={"vendor_address": ("like", f"{self.vendor_address[:5]}%"), "status": "Completed", "name": ("!=", self.name), "supplier": ("is", "set")}, fields=["supplier", "vendor_address"])
			if invoices and (best_match := get_best_match_from_list_of_dicts(invoices, self.vendor_address, "vendor_address")):
				self.supplier = best_match.get("supplier")

		# 2.Get from OCR Request
		if not self.supplier and self.ocr_request:
			ocr_data = self.get_ocr_analysis()
			# 2.1 Find VENDOR_URL
			if ocr_data.get("VENDOR_URL"):
				if matching_ocr_requests := frappe.get_all("OCR Request", filters={"analysis": ("like", f"%{ocr_data.get('VENDOR_URL')}%"), "name": ("!=", self.ocr_request)}, limit=1, pluck="name"):
					self.supplier = frappe.db.get_value("Pending Purchase Invoice", dict(ocr_request=matching_ocr_requests[0]))


	def calculate_due_date(self):
		if not self.due_date and self.supplier:
			try:
				self.due_date = get_due_date(
					posting_date=self.bill_date or nowdate(),
					party_type="Supplier",
					party=self.supplier,
					company=self.company,
					bill_date=self.bill_date
				)
			except Exception:
				pass

	def set_status(self, commit=False):
		status = "Pending"
		if frappe.db.exists("Purchase Order", dict(pending_purchase_invoice=self.name, docstatus=("!=", 2))):
			status = "In Progress"
		if frappe.db.exists("Purchase Invoice", dict(pending_purchase_invoice=self.name, docstatus=("=", 1))):
			status = "Completed"

		self.status = status
		if commit:
			self.db_set("status", status)

	@frappe.whitelist()
	def calculate_totals(self):
		self.net_total = 0.0
		self.tax_total = 0.0
		self.grand_total = 0.0
		try:
			po = frappe.new_doc("Purchase Order")
			for item in self.items:
				po.append("items", frappe.copy_doc(item).as_dict())
			po.update(self.as_dict())
			po.run_method("set_missing_values")
			# append taxes
			po.set("taxes", [])
			if po.taxes_and_charges:
				po.append_taxes_from_master()
			else:
				po.append_taxes_from_item_tax_template()

			po.run_method("calculate_taxes_and_totals")

			self.net_total = po.net_total or 0.0
			self.tax_total = po.total_taxes_and_charges or 0.0
			self.grand_total = po.grand_total or 0.0
		except Exception:
			frappe.clear_messages()


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
	def get_document_item_lines(self, doctype, selected_documents, allow_child_item_selection, filtered_line_items):
		result = {
			"items": [],
			"supplier": None,
			"company": None
		}

		for selected_document in selected_documents:
			doc = frappe.get_doc(doctype, selected_document)

			if result["company"] and doc.company != result["company"]:
				frappe.throw(_("Please select documents linked to the same company"))

			if result["supplier"] and doc.supplier != result["supplier"]:
				frappe.throw(_("Please select documents linked to the same supplier"))

			result["supplier"] = doc.supplier
			result["company"] = doc.company

			if sbool(allow_child_item_selection):
				for item in doc.items:
					if item.name in filtered_line_items:
						result["items"].append(item)
			else:
				result["items"].extend(doc.items)

		return result

	def get_purchase_invoice(self):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice as make_purchase_invoice_from_po
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice as make_purchase_invoice_from_pr

		doc = frappe.new_doc("Purchase Invoice")
		doc.ignore_pricing_rule = 1

		for item in self.items:
			if item.reference_doctype == "Purchase Order":
				make_purchase_invoice_from_po(item.reference_docname, doc)
			elif item.reference_doctype == "Purchase Receipt":
				make_purchase_invoice_from_pr(item.reference_docname, doc)


		for field in frappe.get_meta(self.doctype).fields:
			if field.fieldname in EXCLUDED_FIELDS:
				continue
			if field.fieldtype in data_fieldtypes:
				doc.update({field.fieldname: self.get(field.fieldname)})

		for item in self.items:
			for doc_item in doc.items:
				if doc_item.po_detail == item.row:
					for field in ["rate", "qty", "cost_center", "project"]:
						if doc_item.get(field) != item.get(field):
							doc_item.set(field, item.get(field))


		doc.run_method("set_missing_values")
		doc.set("taxes", [])
		if doc.taxes_and_charges:
			doc.append_taxes_from_master()
		else:
			doc.append_taxes_from_item_tax_template()

		doc.run_method("calculate_taxes_and_totals")

		return doc

	@frappe.whitelist()
	def create_purchase_invoice(self, submit=False):
		for item in self.items:
			if not frappe.db.get_value(item.reference_doctype, item.reference_docname, "docstatus") == 1:
				frappe.throw(_("Please submit {0}: {1} before trying to create the corresponding invoice").format(_(item.reference_doctype).lower(), item.reference_docname))

		doc = self.get_purchase_invoice()
		doc.pending_purchase_invoice = self.name
		doc.insert()

		if sbool(submit):
			doc.submit()

		return doc


	@frappe.whitelist()
	def create_purchase_order(self, submit=False):
		doc = make_purchase_order(self.name)
		doc.insert()

		if sbool(submit):
			doc.submit()

		return doc

	def append_matched_orders(self):
		matched_orders = self.get_matched_orders()
		for matched_order in matched_orders:
			doc = frappe.get_doc("Purchase Order", matched_order)
			for item in doc.items:
				row = frappe.copy_doc(item).as_dict()
				row["reference_doctype"] = doc.doctype
				row["reference_docname"] = doc.name
				row["row"] = item.name
				self.append("items", row)

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

		if self.company:
			query = query.where(purchase_order_dt.company == self.company)

		open_orders = query.run(as_dict=True)

		def find_purchase_order_correspondance(purchase_order, data):
			return re.search(r"(?<![\w\d])" + re.escape(purchase_order) + r"(?![\w\d])", data, re.IGNORECASE)

		matched_orders = set()
		if self.ocr_request:
			ocr_data = self.get_ocr_analysis()
			if ocr_data.get("PO_NUMBER"):
				for open_order in open_orders:
					if find_purchase_order_correspondance(open_order.name, ocr_data["PO_NUMBER"]):
							matched_orders.add(open_order.name)

			for child in ocr_data.get("items"):
				for open_order in open_orders:
					if find_purchase_order_correspondance(open_order.name, child.get("expense_row") or ""):
						matched_orders.add(open_order.name)
					elif find_purchase_order_correspondance(open_order.order_confirmation_no or "", child.get("expense_row") or ""):
						matched_orders.add(open_order.name)

		return matched_orders

	def get_ocr_analysis(self):
		if not self.ocr_request:
			return {}

		return frappe.get_doc("OCR Request", self.ocr_request).get_data_from_analysis()

	@frappe.whitelist()
	def close_request(self):
		self.db_set("status", "Closed")
		self.run_method("on_close")

	@frappe.whitelist()
	def open_request(self):
		self.status = "Pending"
		self.set_status(True)


def get_best_match_from_list_of_dicts(data, matching_element, key):
	if best_match := next(iter(sorted(
		data,
		key=lambda doc: difflib.SequenceMatcher(
			lambda doc: doc == " ", doc.get(key).lower(), matching_element.lower()
		).ratio(),
		reverse=True,
	))):
		return best_match

	return {}


def make_purchase_order(source_name, target_doc=None, ignore_permissions=False):
	from frappe.model.mapper import get_mapped_doc
	from erpnext.buying.doctype.purchase_order.purchase_order import set_missing_values

	def purchase_invoice_item_condition(doc):
		if not doc.reference_doctype:
			return doc
		else:
			return {}

	def postprocess(source, target_doc):
		target_doc.ignore_pricing_rule = 1

		set_missing_values(source, target_doc)

		if not target_doc.schedule_date:
			target_doc.schedule_date = frappe.utils.nowdate()

		#target_doc.payment_schedule = []
		target_doc.pending_purchase_invoice = source_name

		target_doc.set("taxes", [])

		# append taxes
		if target_doc.taxes_and_charges:
			target_doc.append_taxes_from_master()
		else:
			target_doc.append_taxes_from_item_tax_template()

		target_doc.run_method("set_missing_values")
		target_doc.run_method("calculate_taxes_and_totals")

	def update_source_item(obj, target, source_parent):
		target.pending_purchase_invoice_item = obj.name

	doclist = get_mapped_doc("Pending Purchase Invoice", source_name, 	{
		"Pending Purchase Invoice": {
			"doctype": "Purchase Order",
		},
		"Pending Purchase Invoice Item": {
			"doctype": "Purchase Order Item",
			"postprocess": update_source_item,
			"condition": purchase_invoice_item_condition,
		}
	}, target_doc, postprocess, ignore_permissions=ignore_permissions)

	return doclist


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_purchase_documents(doctype, txt, searchfield, start, page_len, filters):
	fields = ["name", "supplier", "grand_total"]
	if doctype == "Purchase Order":
		fields.append("transaction_date")
	elif doctype == "Purchase Receipt":
		fields.append("posting_date")

	return frappe.get_list(doctype, filters=filters, fields=fields)


@frappe.whitelist()
def get_documents_child_items(doctype, filters, limit_page_length):
	query_filters = frappe.parse_json(filters)
	if not [f for f in query_filters if f[0] == "parent"]:
		query_filters.append(["parent", "in", []])

	purchase_doc_dt = frappe.qb.DocType(doctype)
	purchase_doc_item_dt = frappe.qb.DocType(f"{doctype} Item")

	query = frappe.qb.get_query(
		table=f"{doctype} Item",
		filters=query_filters,
		fields=["name", "parent"],
		limit=limit_page_length,
	)

	query = (
		query.left_join(purchase_doc_dt)
		.on(purchase_doc_item_dt.parent == purchase_doc_dt.name)
		.select(purchase_doc_dt.supplier)
	)

	if doctype == "Purchase Order":
		query = query.select(purchase_doc_dt.transaction_date)
	elif doctype == "Purchase Receipt":
		query = query.select(purchase_doc_dt.posting_date)

	query = query.select(purchase_doc_item_dt.item_code, purchase_doc_item_dt.qty, purchase_doc_item_dt.net_amount, purchase_doc_item_dt.cost_center)

	if doctype == "Purchase Order":
		query = query.orderby(purchase_doc_dt.transaction_date, order=Order.desc)
	elif doctype == "Purchase Receipt":
		query = query.orderby(purchase_doc_dt.posting_date, order=Order.desc)

	return query.run(as_dict=True)



def register_purchase_order_items(doc, method=None):
	if not doc.pending_purchase_invoice:
		return

	for item in doc.items:
		if item.pending_purchase_invoice_item:
			if not frappe.db.get_value("Pending Purchase Invoice Item", item.pending_purchase_invoice_item, "row"):
				frappe.db.set_value("Pending Purchase Invoice Item", item.pending_purchase_invoice_item, "row", item.name)
				frappe.db.set_value("Pending Purchase Invoice Item", item.pending_purchase_invoice_item, "reference_doctype", item.parenttype)
				frappe.db.set_value("Pending Purchase Invoice Item", item.pending_purchase_invoice_item, "reference_docname", item.parent)


def set_pending_purchase_order_status(doc, method=None):
	if not doc.pending_purchase_invoice:
		return

	frappe.get_doc("Pending Purchase Invoice", doc.pending_purchase_invoice).run_method("set_status", commit=True)