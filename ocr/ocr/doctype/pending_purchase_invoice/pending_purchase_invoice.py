# Copyright (c) 2024, Dokos SAS and contributors
# For license information, please see license.txt

from frappe.model.meta import data_fieldtypes, default_fields

from frappe.query_builder import Order
from frappe import _
from frappe.utils import flt, nowdate
from erpnext.controllers.accounts_controller import AccountsController
from erpnext.accounts.party import get_due_date

import frappe
from frappe.utils import sbool


EXCLUDED_FIELDS = [*default_fields, "status"]

class PendingPurchaseInvoice(AccountsController):
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
		net_total: DF.Currency
		ocr_request: DF.Link | None
		posting_date: DF.Date
		status: DF.Literal["Pending", "In Progress", "Completed"]
		supplier: DF.Link
		supplier_grand_total: DF.Currency
		supplier_net_amount: DF.Currency
		supplier_tax_amount: DF.Currency
		tax_category: DF.Link | None
		tax_total: DF.Currency
		taxes_and_charges: DF.Link | None
		title: DF.Data | None
	# end: auto-generated types

	def validate(self):
		self.title = f"{self.supplier}"[:140] if self.bill_no else f"{self.supplier} : {self.bill_no}"[:140]
		self.calculate_due_date()
		self.calculate_totals()

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

	def set_pending_purchase_order_status(self, commit=False):
		status = "Pending"
		if frappe.db.exists("Purchase Order", dict(pending_purchase_invoice=self.name, docstatus=("!=", 2))):
			status = "In Progress"
		if frappe.db.exists("Purchase Invoice", dict(pending_purchase_invoice=self.name, docstatus=("=", 1))):
			status = "Completed"

		self.status = status
		if commit:
			self.db_set("status", status)

	def calculate_totals(self):
		self.calculate_net_total()
		self.calculate_taxes()
		self.calculate_grand_total()

	def calculate_net_total(self):
		self.net_total = sum(flt(i.amount) for i in self.items)

	def calculate_taxes(self):
		try:
			doc = make_purchase_order(self.name, simulation=True)
			doc.run_method("set_missing_values")
			doc.run_method("calculate_taxes_and_totals")
			self.tax_total = doc.total_taxes_and_charges
		except Exception:
			frappe.clear_messages()

	def calculate_grand_total(self):
		self.grand_total = flt(self.net_total) + flt(self.tax_total)

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

		doc.run_method("set_missing_values")
		doc.run_method("calculate_taxes_and_totals")

		doc.set("taxes", [])

		# 	# append taxes
		doc.append_taxes_from_master()
		doc.append_taxes_from_item_tax_template()

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

	# def get_matched_orders(self):
	# 	purchase_order_dt = frappe.qb.DocType("Purchase Order")
	# 	purchase_invoice_item_dt = frappe.qb.DocType("Purchase Invoice Item")

	# 	subquery = (
	# 		frappe.qb.from_(purchase_invoice_item_dt)
	# 		.select(purchase_invoice_item_dt.name)
	# 		.where(purchase_invoice_item_dt.docstatus.lt(2))
	# 		.where(purchase_invoice_item_dt.purchase_order == purchase_order_dt.name)
	# 	)

	# 	query = (
	# 		frappe.qb.from_(purchase_order_dt)
	# 		.select(purchase_order_dt.name, purchase_order_dt.net_total, purchase_order_dt.order_confirmation_no, purchase_order_dt.company)
	# 		.where((purchase_order_dt.docstatus == 1) & (purchase_order_dt.per_billed.lt(100)) & (purchase_order_dt.status.notin(["Closed", "Completed"])))
	# 		.where(ExistsCriterion(subquery).negate())
	# 	)

	# 	if self.supplier:
	# 		query = query.where(purchase_order_dt.supplier == self.supplier)

	# 	open_orders = query.run(as_dict=True)

	# 	matched_orders = set()
	# 	if self.get_creation_mode() == "Get items from purchase orders recognized by the OCR":
	# 		for child in self.line_items_mapping:
	# 			for open_order in open_orders:
	# 				if re.search(r"(?<![\w\d])" + re.escape(open_order.name) + r"(?![\w\d])", child.get("expense_row") or "", re.IGNORECASE):
	# 					matched_orders.add(open_order.name)
	# 				elif re.search(r"(?<![\w\d])" + re.escape(open_order.order_confirmation_no or "") + r"(?![\w\d])", child.get("expense_row") or "", re.IGNORECASE):
	# 					matched_orders.add(open_order.name)
	# 	elif open_orders:
	# 		if closest_order := min(open_orders, key=lambda x:abs(x.net_total - self.net_total)):
	# 			matched_orders.add(closest_order.name)

	# 	return matched_orders

	# def find_line_items_correspondence(self):
	# 	for line in self.line_items_mapping:
	# 		if line.item_code:
	# 			continue

	# 		line.item_code = self.get_supplier_item(line.get("item")) or self.get_previous_correspondance(line.get("item"))

	# def get_purchase_invoice_qty(self, row):
	# 	if row.get("unit_price") and row.get("price") and row.get("price") != row.get("unit_price"):
	# 		return flt(row.get("price") ) / flt(row.get("unit_price"))

	# 	elif row.get("quantity"):
	# 		return row.get("quantity")

	# 	return 1

	# def get_purchase_invoice_uom(self, row):
	# 	expense_row = row.get("EXPENSE_ROW")

	# 	if expense_row and (before_unit_price := re.search(r".+?(?=" + re.escape(row.get("unit_price")) + r")", expense_row, re.IGNORECASE)):
	# 		for section in reversed(before_unit_price[0].strip().split()):
	# 			if not section.isnumeric() and frappe.db.get_value("UOM", section):
	# 				return section

	# 	return frappe.db.get_single_value("Stock Settings", "stock_uom")

	# def get_supplier_item(self, item):
	# 	if not self.supplier:
	# 		return

	# 	return frappe.db.get_value(
	# 		"Item Supplier",
	# 		dict(
	# 			supplier=self.supplier,
	# 			supplier_part_no=item
	# 		),
	# 		"parent"
	# 	)

	# def get_previous_correspondance(self, item):
	# 	if not self.company or not self.supplier:
	# 		return

	# 	ocr_request = frappe.qb.DocType("OCR Request")
	# 	ocr_request_line_mapping = frappe.qb.DocType("OCR Line Items Mapping")

	# 	query = (
	# 		frappe.qb.from_(ocr_request)
	# 		.left_join(ocr_request_line_mapping)
	# 		.on(ocr_request.name == ocr_request_line_mapping.parent)
	# 		.select(ocr_request_line_mapping.item_code, ocr_request.name)
	# 		.where(ocr_request.company == self.company)
	# 		.where(ocr_request.supplier == self.supplier)
	# 		.where(ocr_request_line_mapping.item == item)
	# 		.where(ocr_request_line_mapping.item_code.isnotnull())
	# 		.orderby(ocr_request.modified, order=Order.desc)
	# 	)
	# 	if result := query.run(as_dict=True):
	# 		return result[0].item_code


def make_purchase_order(source_name, target_doc=None, ignore_permissions=False, simulation=False):
	from frappe.model.mapper import get_mapped_doc
	from erpnext.buying.doctype.purchase_order.purchase_order import set_missing_values

	def purchase_invoice_item_condition(doc):
		if not simulation:
			if not doc.reference_doctype:
				return doc
			else:
				return {}

		return doc

	def postprocess(source, target_doc):
		target_doc.ignore_pricing_rule = 1

		set_missing_values(source, target_doc)

		if not target_doc.schedule_date:
			target_doc.schedule_date = frappe.utils.nowdate()

		#target_doc.payment_schedule = []
		target_doc.pending_purchase_invoice = source_name

		target_doc.set("taxes", [])

		# 	# append taxes
		target_doc.append_taxes_from_master()
		target_doc.append_taxes_from_item_tax_template()

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