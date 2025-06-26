# Copyright (c) 2024, Dokos SAS and contributors
# For license information, please see license.txt

import re
import difflib
from frappe.model.document import Document
from pypika.terms import ExistsCriterion

from frappe.model.meta import data_fieldtypes, default_fields, child_table_fields

from frappe.query_builder import Order
from frappe import _
from frappe.utils import flt, fmt_money, nowdate
from erpnext.accounts.party import get_due_date, set_taxes, get_address_tax_category
from frappe.contacts.doctype.address.address import get_default_address
from frappe.model.workflow import get_transitions, get_workflow, has_approval_access, apply_workflow

import frappe
from frappe.utils import sbool

ItemDetailsCtx = frappe._dict
ItemDetails = frappe._dict


EXCLUDED_FIELDS = [*default_fields, *child_table_fields, "status"]

REFERENCE_FIELDS = {
	"Purchase Order": {"reference_docname": "purchase_order", "row": "po_detail"},
	"Purchase Receipt": {"reference_docname": "purchase_receipt", "row": "pr_detail"},
}

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
		is_return: DF.Check
		items: DF.Table[PendingPurchaseInvoiceItem]
		name: DF.Int | None
		net_total: DF.Currency
		ocr_basket: DF.Link | None
		ocr_request: DF.Link | None
		original_invoice: DF.Link | None
		posting_date: DF.Date
		purchase_order_number: DF.Data | None
		status: DF.Literal["Pending", "In Progress", "Ready", "Completed", "Closed"]
		supplier: DF.Link
		supplier_grand_total: DF.Currency
		supplier_name: DF.Data | None
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
		self.set_tax_category()
		self.set_tax_template()
		self.set_missing_values_in_items()

		if self.supplier:
			self.title = f"{self.supplier} : {self.bill_no}"[:140] if self.bill_no else f"{self.supplier}"[:140]
		else:
			self.title = _("Missing Supplier")
		self.calculate_due_date()

		if not self.items:
			self.append_matched_receipts()

		if not self.items:
			self.append_matched_orders()

	def on_update(self):
		self.calculate_totals()
		self.auto_reconcile()

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
					posting_date=self.bill_date or self.posting_date or nowdate(),
					party_type="Supplier",
					party=self.supplier,
					company=self.company,
					bill_date=self.bill_date
				)
			except Exception:
				pass

	def set_status(self, commit=False):
		status = "Pending"
		purchase_orders = frappe.get_all("Purchase Order", dict(pending_purchase_invoice=self.name, docstatus=("!=", 2)), pluck="docstatus")
		if purchase_orders:
			status = "In Progress"
		if self.items and all([po for po in purchase_orders if po == 1]):
			status = "Ready"
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
			if pi := frappe.db.exists("Purchase Invoice", dict(pending_purchase_invoice=self.name)):
				doc = frappe.get_doc("Purchase Invoice", pi)
			else:
				doc = frappe.new_doc("Purchase Invoice")
				for item in self.items:
					doc.append("items", frappe.copy_doc(item).as_dict())
				doc.update(self.as_dict())
				doc.run_method("set_missing_values")
				# append taxes
				doc.set("taxes", [])
				if doc.taxes_and_charges:
					doc.append_taxes_from_master()
				else:
					doc.append_taxes_from_item_tax_template()

				doc.run_method("calculate_taxes_and_totals")

			self.net_total = doc.net_total or 0.0
			self.tax_total = doc.total_taxes_and_charges or 0.0
			self.grand_total = doc.grand_total or 0.0
		except Exception:
			frappe.clear_messages()

	def commit_totals(self):
		self.db_set("net_total", self.net_total)
		self.db_set("tax_total", self.tax_total)
		self.db_set("grand_total", self.grand_total)

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

	def get_purchase_invoice(self, purchase_order_is_mandatory=True):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice as make_purchase_invoice_from_po
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice as make_purchase_invoice_from_pr

		doc = frappe.new_doc("Purchase Invoice")
		doc.ignore_pricing_rule = 1
		doc.set_posting_time = 1
		doc.posting_date = self.posting_date

		if purchase_order_is_mandatory:
			if self.items[0].reference_doctype == "Purchase Order":
				make_purchase_invoice_from_po(self.items[0].reference_docname, doc)
			elif self.items[0].reference_doctype == "Purchase Receipt":
				make_purchase_invoice_from_pr(self.items[0].reference_docname, doc)

		doc_items = doc.items

		def get_doc_item(item):
			name = REFERENCE_FIELDS.get(item.reference_doctype, {}).get("row")
			for doc_item in doc_items:
				if doc_item.get(name) == item.row:
					return frappe.copy_doc(doc_item).as_dict()
			else:
				return frappe._dict()

		doc.set("items", [])
		for item in self.items:
			ppi_row = frappe.copy_doc(item).as_dict()
			if self.is_return:
				doc.append("items", ppi_row)
			else:
				doc_item = get_doc_item(item)
				new_row = doc_item.update(ppi_row)
				for key, value in REFERENCE_FIELDS.get(item.reference_doctype, {}).items():
					new_row[value] = item.get(key)

				doc.append("items", new_row)

		doc.is_return = bool(self.is_return)
		if doc.is_return and self.original_invoice:
			doc.return_against = self.original_invoice
			doc.update_outstanding_for_self = 0

		for field in frappe.get_meta(self.doctype).fields:
			if field.fieldname in EXCLUDED_FIELDS:
				continue
			if field.fieldtype in data_fieldtypes:
				doc.update({field.fieldname: self.get(field.fieldname)})

		# Explicitely remove discounts coming from POs
		doc.additional_discount_percentage = 0.0
		doc.discount_amount = 0.0

		doc.run_method("set_missing_values")
		doc.set("taxes", [])
		if doc.taxes_and_charges:
			doc.append_taxes_from_master()
		else:
			doc.append_taxes_from_item_tax_template()

		doc.run_method("calculate_taxes_and_totals")

		return doc

	def create_purchase_invoice(self, submit=False):
		if (purchase_order_is_mandatory := not self.is_return and not frappe.db.get_single_value("OCR Settings", "no_purchase_order")):
			for item in self.items:
				if not frappe.db.get_value(item.reference_doctype, item.reference_docname, "docstatus") == 1:
					frappe.throw(_("Please submit {0}: {1} before trying to create the corresponding invoice").format(_(item.reference_doctype).lower(), item.reference_docname))

		doc = self.get_purchase_invoice(purchase_order_is_mandatory)
		doc.pending_purchase_invoice = self.name
		doc.insert(ignore_mandatory=True)

		if submit:
			if workflow_actions := self.get_workflow_actions("Purchase Invoice", doc):
				if len(workflow_actions) == 1:
					apply_workflow(doc, workflow_actions[0])
			else:
				doc.submit()

		return doc


	def create_purchase_order(self, submit=False):
		doc = make_purchase_order(self.name)
		doc.insert()

		if submit:
			if workflow_actions := self.get_workflow_actions("Purchase Order", doc):
				if len(workflow_actions) == 1:
					apply_workflow(doc, workflow_actions[0])
			else:
				doc.submit()

		return doc

	def append_matched_orders(self):
		if frappe.db.get_single_value("OCR Settings", "reconcile_with_purchase_receipts"):
			return

		try:
			matched_orders = self.get_matched_orders()
			for matched_order in matched_orders:
				doc = frappe.get_doc("Purchase Order", matched_order)
				for item in doc.items:
					row = frappe.copy_doc(item).as_dict()
					row["reference_doctype"] = doc.doctype
					row["reference_docname"] = doc.name
					row["row"] = item.name
					self.append("items", row)
		except Exception:
			self.log_error()

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
		if not self.open_receipts and len(open_orders) == 1:
			return open_orders

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

		if not matched_orders:
			for open_order in open_orders:
				if open_order.get("net_total") == self.supplier_net_amount:
					matched_orders.add(open_order.name)
					break

		return matched_orders

	def append_matched_receipts(self):
		matched_receipts = self.get_matched_receipts()

		try:
			for matched_receipt in matched_receipts:
				doc = frappe.get_doc("Purchase Receipt", matched_receipt)
				for item in doc.items:
					row = frappe.copy_doc(item).as_dict()
					row["reference_doctype"] = doc.doctype
					row["reference_docname"] = doc.name
					row["row"] = item.name

					if row["qty"] == 1:
						row["rate"] = min(row["rate"], self.supplier_net_amount)

					row["amount"] = row["qty"] * row["rate"]

					self.append("items", row)
		except Exception:
			self.log_error()


	def get_matched_receipts(self):
		purchase_receipt_dt = frappe.qb.DocType("Purchase Receipt")
		purchase_receipt_item_dt = frappe.qb.DocType("Purchase Receipt Item")
		purchase_order_dt = frappe.qb.DocType("Purchase Order")
		purchase_invoice_item_dt = frappe.qb.DocType("Purchase Invoice Item")

		subquery = (
			frappe.qb.from_(purchase_invoice_item_dt)
			.select(purchase_invoice_item_dt.name)
			.where(purchase_invoice_item_dt.docstatus.lt(2))
			.where(purchase_invoice_item_dt.purchase_order == purchase_receipt_dt.name)
		)

		query = (
			frappe.qb.from_(purchase_receipt_dt)
			.right_join(purchase_receipt_item_dt)
			.on(purchase_receipt_dt.name == purchase_receipt_item_dt.parent)
			.left_join(purchase_order_dt)
			.on(purchase_order_dt.name == purchase_receipt_item_dt.purchase_order)
			.select(purchase_receipt_dt.name, purchase_receipt_dt.net_total, purchase_receipt_dt.supplier_delivery_note, purchase_receipt_dt.company, purchase_order_dt.name.as_("purchase_order"), purchase_order_dt.order_confirmation_no)
			.where((purchase_receipt_dt.docstatus == 1) & (purchase_receipt_dt.per_billed.lt(100)) & (purchase_receipt_dt.status.notin(["Closed", "Completed"])))
			.where(ExistsCriterion(subquery).negate())
		)

		if self.supplier:
			query = query.where(purchase_receipt_dt.supplier == self.supplier)

		if self.company:
			query = query.where(purchase_receipt_dt.company == self.company)

		open_receipts = query.run(as_dict=True)
		self.open_receipts = open_receipts # used to return order if single

		def find_purchase_order_correspondance(purchase_order, data):
			return re.search(r"(?<![\w\d])" + re.escape(purchase_order) + r"(?![\w\d])", data, re.IGNORECASE)

		matched_orders = set()
		if self.ocr_request:
			ocr_data = self.get_ocr_analysis()
			if ocr_data.get("PO_NUMBER"):
				for open_order in open_receipts:
					if find_purchase_order_correspondance(open_order.name, ocr_data["PO_NUMBER"]):
							matched_orders.add(open_order.name)
					elif find_purchase_order_correspondance(open_order.purchase_order, ocr_data["PO_NUMBER"]):
							matched_orders.add(open_order.name)

			for child in ocr_data.get("items"):
				for open_order in open_receipts:
					if find_purchase_order_correspondance(open_order.name, child.get("expense_row") or ""):
						matched_orders.add(open_order.name)
					elif find_purchase_order_correspondance(open_order.order_confirmation_no or open_order.supplier_delivery_note or "", child.get("expense_row") or ""):
						matched_orders.add(open_order.name)

		# Case 1: Perfect match between receipt and invoice
		if not matched_orders:
			for open_order in open_receipts:
				if self.purchase_order_number and (self.purchase_order_number != open_order.get("purchase_order")):
					continue

				if open_order.get("net_total") == flt(self.supplier_net_amount):
					matched_orders.add(open_order.name)
					break

		# Case 2: Perfect match between receipt and invoice
		if not matched_orders and flt(self.supplier_net_amount or 0.0) > 0:
			for open_order in open_receipts:
				if self.purchase_order_number and (self.purchase_order_number != open_order.get("purchase_order")):
					continue

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

	def set_tax_category(self):
		if not self.tax_category or not self.supplier:
			tax_category = frappe.db.get_value("Supplier", self.supplier, "tax_category")
			party_address = get_default_address("Supplier", self.supplier)
			self.tax_category = get_address_tax_category(
				tax_category,
				party_address,
				party_address
			)

	def set_tax_template(self):
		if not self.taxes_and_charges:
			party_address = get_default_address("Supplier", self.supplier) # Todo: avoid duplicate query
			self.taxes_and_charges = set_taxes(
				party=self.supplier,
				party_type="Supplier",
				posting_date=self.posting_date,
				company=self.company,
				customer_group=None,
				supplier_group=None,
				tax_category=self.tax_category,
				billing_address=party_address,
				shipping_address=party_address,
				use_for_shopping_cart=0,
			)

	def get_workflow_actions(self, doctype, doc):
		if frappe.db.get_value("Workflow", dict(document_type=doctype, is_active=True)):
			try:
				workflow = get_workflow(doctype)
				if hasattr(doc, "__islocal"):
					delattr(doc, "__islocal")
				doc.set(workflow.workflow_state_field, workflow.states[0].state)
				actions = [
					t.get("action")
					for t in get_transitions(doc, raise_exception=True)
					if has_approval_access(frappe.session.user, doc, t)
				]
				return actions
			except Exception:
				print("Workflow Error", frappe.get_traceback())
				return []

		return []


	def set_missing_values_in_items(self):
		for item in self.items:
			for field in ["project", "cost_center"]:
				if self.get(field) and not item.get(field):
					item.set(field, self.get(field))


	@frappe.whitelist()
	def get_return_invoice(self, original_invoice):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		return make_return_doc("Purchase Invoice", original_invoice)

	def auto_reconcile(self):
		if not self.items:
			return

		settings = frappe.get_single("OCR Settings")
		if not settings.reconcile_with_purchase_receipts: # type: ignore
			return

		if frappe.db.exists("Purchase Invoice", dict(pending_purchase_invoice=self.name, docstatus=("!=", 2))):
			return

		# Do not automatically submit if amount do not match
		min_amount = min(
			flt(self.supplier_net_amount) - flt(settings.max_difference_amount),
			flt(self.supplier_net_amount) * (1 - flt(settings.max_difference_percentage_on_net_total) / 100)
		)

		max_amount = min(
			flt(self.supplier_net_amount) + flt(settings.max_difference_amount),
			flt(self.supplier_net_amount) * (1 + flt(settings.max_difference_percentage_on_net_total) / 100)
		)

		precision = frappe.db.get_default("currency_precision")

		if flt(min_amount, precision=precision) <= flt(self.net_total, precision=precision) <= flt(max_amount, precision=precision): # type: ignore
			if difference := flt(self.supplier_net_amount) - flt(self.net_total):
				for item in self.items:
					if item.qty == 1:
						item.rate += difference
						self.add_comment(_("The rate at line {1} has been ajusted to {0} to match the supplier's invoice.").format(fmt_money(item.rate, currency=self.currency), item.idx))
						break

			self.calculate_totals()
			if flt(self.supplier_net_amount, precision=precision) == flt(self.net_total, precision=precision) and flt(self.supplier_grand_total, precision=precision) == flt(self.grand_total, precision=precision): # type: ignore
				self.add_comment(text=_("A purchase invoice has been automatically created for this invoice."))
				#self.create_purchase_invoice(submit=settings.auto_submit_purchase_invoices) # type: ignore

			self.add_comment(text=_("The automatic reconciliation has failed because the totals do not match"))

		else:
			self.add_comment(text=_("The automatic reconciliation has failed for the following reasons because the net total is higher than {0} or lower than {1}").format(fmt_money(max_amount, currency=self.currency), fmt_money(min_amount, currency=self.currency)))

		self.commit_totals()


@frappe.whitelist()
def get_item_details(row, company, tax_category=None):
	from erpnext.accounts.doctype.budget.budget import get_item_details as _get_item_details
	from erpnext.stock.get_item_details import get_item_tax_template

	row = frappe.parse_json(row)
	item_code = row.get("item_code")
	item = frappe.get_cached_doc("Item", item_code)

	cost_center, expense_account = _get_item_details(frappe._dict({
		"item_code": item_code,
		"company": company
	}))

	description = frappe.db.get_value("Item", item_code, "description")

	ctx: ItemDetailsCtx = {
		"company": company,
		"tax_category": tax_category,
		"base_net_rate": row.get("base_rate"), # type: ignore
		"doctype": "Purchase Invoice",
		"child_doctype": "Purchase Invoice Item"
	}

	out = ItemDetails()
	get_item_tax_template(ctx, item, out)
	return {
		"cost_center": cost_center,
		"expense_account": expense_account,
		"description": description,
		"item_tax_template": out.get("item_tax_template")
	}


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
		target_doc.department = source.get("department")

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

	doclist = get_mapped_doc("Pending Purchase Invoice", source_name, {
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
	fields = ["name", "supplier", "grand_total", "status"]
	if doctype == "Purchase Order":
		fields.append("transaction_date")
	elif doctype == "Purchase Receipt":
		fields.append("posting_date")

	if txt:
		filters["name"] = ("like", f"%{txt}%")

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


def auto_match_with_purchase_receipt(doc, method=None):
	for pending_purchase_invoice in frappe.get_all("Pending Purchase Invoice", filters={"supplier": doc.supplier, "status": "Pending"}):
		try:
			frappe.get_doc("Pending Purchase Invoice").save()
		except Exception:
			pass


def set_pending_purchase_order_status(doc, method=None):
	if not doc.pending_purchase_invoice:
		return

	frappe.get_doc("Pending Purchase Invoice", doc.pending_purchase_invoice).run_method("set_status", commit=True)


def deduplicate_items(items):
	po_detail = set()
	pr_detail = set()

	output = []

	for item in items:
		if item.po_detail and item.po_detail in po_detail:
			continue
		elif item.po_detail:
			po_detail.add(item.po_detail)

		if item.pr_detail and item.pr_detail in pr_detail:
			continue
		elif item.pr_detail:
			pr_detail.add(item.pr_detail)

		output.append(item)

	return output


def validate_total(doc, method):
	if not doc.pending_purchase_invoice:
		return

	if frappe.db.get_single_value("OCR Settings", "block_if_grand_total_exceeds_pending_pi"):
		if doc.grand_total > frappe.db.get_value("Pending Purchase Invoice", doc.pending_purchase_invoice, "supplier_grand_total"):
			frappe.throw(_("The invoice grand total exceeds the supplier provided grand total. You are not allowed to create this purchase invoice."))

	if frappe.db.get_single_value("OCR Settings", "block_if_net_total_exceeds_pending_pi"):
		if doc.net_total > frappe.db.get_value("Pending Purchase Invoice", doc.pending_purchase_invoice, "supplier_net_amount"):
			frappe.throw(_("The invoice net total exceeds the supplier provided net total. You are not allowed to create this purchase invoice."))


@frappe.whitelist()
def create_purchase_invoice(docname, submit=False):
	return frappe.get_doc("Pending Purchase Invoice", docname).run_method("create_purchase_invoice", submit=sbool(submit))


@frappe.whitelist()
def create_purchase_order(docname, submit=False):
	return frappe.get_doc("Pending Purchase Invoice", docname).run_method("create_purchase_order", submit=sbool(submit))


@frappe.whitelist()
def get_settings():
	settings = frappe.get_single("OCR Settings")
	return {
		"reconcile_with_purchase_receipts": settings.reconcile_with_purchase_receipts # type: ignore
	}