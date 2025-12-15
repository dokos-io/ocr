# Copyright (c) 2024, Dokos SAS and contributors
# For license information, please see license.txt

import json
import time
from typing import TYPE_CHECKING
from collections import defaultdict
import re
import difflib
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from erpnext.controllers.accounts_controller import merge_taxes
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from pypika.terms import ExistsCriterion

from frappe.model.meta import data_fieldtypes, default_fields, child_table_fields

from frappe.query_builder import Order
from frappe import _
from frappe.utils import cint, flt, fmt_money, nowdate
from erpnext.accounts.party import get_due_date, set_taxes, get_address_tax_category
from frappe.contacts.doctype.address.address import get_default_address
from frappe.model.workflow import get_transitions, get_workflow, has_approval_access, apply_workflow

import frappe
from frappe.utils import sbool

if TYPE_CHECKING:
	from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
	from erpnext.accounts.doctype.purchase_invoice_item.purchase_invoice_item import PurchaseInvoiceItem
	from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder
	from ocr.ocr.doctype.ocr_settings.ocr_settings import OCRSettings

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

	def before_save(self):
		self.calculate_totals()

	def on_update(self):
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
					self.supplier = str(frappe.db.get_value("Pending Purchase Invoice", dict(ocr_request=matching_ocr_requests[0])))


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
			self.db_set("status", status, notify=True, commit=True)

	@frappe.whitelist()
	def calculate_totals(self):
		self.net_total = 0.0
		self.tax_total = 0.0
		self.grand_total = 0.0
		try:
			if pi := frappe.db.exists("Purchase Invoice", dict(pending_purchase_invoice=self.name)):
				doc: PurchaseInvoice = frappe.get_doc("Purchase Invoice", pi) # type: ignore
			else:
				doc: PurchaseInvoice = frappe.new_doc("Purchase Invoice") # type: ignore
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
			doc: PurchaseOrder | PurchaseInvoice = frappe.get_doc(doctype, selected_document) # type: ignore

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

		doc: PurchaseInvoice = frappe.new_doc("Purchase Invoice") # type: ignore
		doc.ignore_pricing_rule = 1

		if purchase_order_is_mandatory:
			if self.items[0].reference_doctype == "Purchase Order":
				make_purchase_invoice_from_po(self.items[0].reference_docname, doc)
			elif self.items[0].reference_doctype == "Purchase Receipt":
				make_purchase_invoice_from_pr(self.items[0].reference_docname, doc)


		doc.set_posting_time = 1
		doc.posting_date = self.posting_date

		doc_items = doc.items

		def get_doc_item(item):
			name = REFERENCE_FIELDS.get(item.reference_doctype, {}).get("row")
			for doc_item in doc_items:
				if doc_item.get(name) == item.row:
					return frappe.copy_doc(doc_item).as_dict()
			else:
				try:
					source_item: PurchaseInvoiceItem = frappe.get_doc(f"{item.reference_doctype} Item", item.row) # type: ignore
					source_item.parenttype = doc.doctype
					return frappe.copy_doc(source_item).as_dict()
				except Exception:
					return frappe._dict()

		doc.set("items", [])
		for item in self.items:
			ppi_row = frappe.copy_doc(item).as_dict()
			if self.is_return:
				doc.append("items", ppi_row)
			else:
				doc_item = get_doc_item(item)
				new_row: dict = doc_item.update(ppi_row) # type: ignore
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

		doc: PurchaseInvoice = self.get_purchase_invoice(purchase_order_is_mandatory)
		doc.pending_purchase_invoice = self.name # type: ignore
		doc.insert(ignore_mandatory=True)

		if submit:
			if workflow_actions := self.get_workflow_actions("Purchase Invoice", doc):
				if len(workflow_actions) == 1:
					apply_workflow(doc, workflow_actions[0])
			else:
				doc.submit()

		return doc


	def create_purchase_order(self, transaction_date=None, submit=False):
		doc: PurchaseOrder = make_purchase_order(self.name)
		doc.transaction_date = transaction_date or nowdate()
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
				doc: PurchaseOrder = frappe.get_doc("Purchase Order", matched_order) # type: ignore
				if doc.currency != self.currency:
					self.currency = doc.currency

				for item in doc.items:
					if item.billed_amt >= item.net_amount:
						continue

					row = frappe.copy_doc(item).as_dict()
					row["reference_doctype"] = doc.doctype
					row["reference_docname"] = doc.name
					row["row"] = item.name
					if row["qty"] == 1:
						rate = row["net_amount"] - row["billed_amt"]
						row["rate"] = min(rate, self.supplier_net_amount)

					row["amount"] = row["qty"] * row["rate"]
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
		if not self.purchase_order_number:
			return

		matched_receipts = self.get_matched_receipts()

		try:
			for matched_receipt in matched_receipts:
				doc = frappe.get_doc("Purchase Receipt", matched_receipt)
				if doc.currency != self.currency:
					self.currency = doc.currency

				for item in doc.items:
					if item.billed_amt >= item.net_amount:
						continue

					row = frappe.copy_doc(item).as_dict()
					row["reference_doctype"] = doc.doctype
					row["reference_docname"] = doc.name
					row["row"] = item.name

					if row["qty"] == 1:
						rate = row["net_amount"] - row["billed_amt"]
						row["rate"] = min(rate, self.supplier_net_amount)

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
		if self.status == "Completed" or not self.items:
			return

		if (not self.is_return or not self.purchase_order_number) or not self.net_total:
			return

		settings: OCRSettings = frappe.get_single("OCR Settings") # type: ignore
		if not settings.reconcile_with_purchase_receipts: # type: ignore
			return

		if frappe.db.exists("Purchase Invoice", dict(pending_purchase_invoice=self.name, docstatus=("!=", 2))):
			return

		pending_invoicing_amount = self.get_pending_invoicing_amount()

		# Do not automatically submit if amount do not match
		max_amount = min(
			flt(pending_invoicing_amount) + flt(settings.max_difference_amount),
			flt(pending_invoicing_amount) * (1 + flt(settings.max_difference_percentage_on_net_total) / 100)
		)

		precision = frappe.db.get_default("currency_precision")

		if flt(self.net_total, precision=precision) <= flt(max_amount, precision=precision): # type: ignore
			self.calculate_totals()

			net_total = abs(flt(self.net_total, precision=precision)) if self.is_return else flt(self.net_total, precision=precision) # type: ignore
			if flt(self.supplier_net_amount, precision=precision) == net_total: # type: ignore
				try:
					doc = self.create_purchase_invoice(submit=settings.auto_submit_purchase_invoices) # type: ignore
					self.add_comment(text=_("Purchase invoice {0} has been automatically created for this invoice.").format(doc.name))
				except Exception as e:
					self.add_comment(text=str(e))
					raise e
			else:
				self.add_comment(text=_("The automatic reconciliation has failed because the totals do not match"))

			self.commit_totals()
			self.set_status()
		else:
			self.add_comment(text=_("The automatic reconciliation has failed for because the net total is higher than {0}").format(fmt_money(max_amount, currency=self.currency)))


	def get_pending_invoicing_amount(self):
		total_per_ref = defaultdict(dict)
		for item in self.items:
			if item.reference_doctype and item.reference_docname and (item.reference_doctype, item.reference_docname) not in total_per_ref:
				doc = frappe.get_doc(item.reference_doctype, item.reference_docname)
				total_per_ref[(item.reference_doctype, item.reference_docname)] = doc.net_total - (flt(doc.per_billed) / 100.0 * doc.net_total)

		return sum(total_per_ref.values())

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
		limit=cint(limit_page_length),
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

	query = query.where(purchase_doc_item_dt.billed_amt < purchase_doc_item_dt.net_amount)

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
	pending_purchase_invoices = frappe.get_list(
		"Pending Purchase Invoice",
		filters={
			"supplier": doc.supplier,
			"status": "Pending",
			"purchase_order_number": ("is", "set"),
		},
		order_by="bill_date ASC",
		fields=["name", "supplier_net_amount"]
	)

	exact_match = [ppi for ppi in pending_purchase_invoices if doc.net_amount == ppi.supplier_net_amount]
	if exact_match:
		pending_purchase_invoices = exact_match[:1]

	for pending_purchase_invoice in pending_purchase_invoices:
		ppi: PendingPurchaseInvoice = frappe.get_doc("Pending Purchase Invoice", pending_purchase_invoice.name) # type: ignore
		ppi.flags.ignore_permissions = True
		ppi.save()


def remove_link_with_pending_purchase_invoices(doc, method=None):
	if method not in ["on_change", "on_cancel"]:
		return

	if method == "on_change" and doc.status != "Closed":
		return

	for pending_purchase_invoice in frappe.get_list(
		"Pending Purchase Invoice",
		filters={
			"supplier": doc.supplier,
			"status": "Pending",
			"purchase_order_number": ("is", "set"),
		},
	):
		ppi: PendingPurchaseInvoice = frappe.get_doc("Pending Purchase Invoice", pending_purchase_invoice.name) # type: ignore
		items = [item.reference_docname for item in ppi.items if item.reference_doctype == "Purchase Receipt"]
		if doc.name in items:
			ppi.items = []
		ppi.flags.ignore_permissions = True
		ppi.save()


def set_pending_purchase_order_status(doc, method=None):
	if not doc.pending_purchase_invoice:
		return

	ppi: PendingPurchaseInvoice = frappe.get_doc("Pending Purchase Invoice", doc.pending_purchase_invoice) # type: ignore
	ppi.run_method("set_status", commit=True)
	ppi.notify_update()


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
def create_purchase_order(docname, transaction_date=None, submit=False):
	return frappe.get_doc("Pending Purchase Invoice", docname).run_method("create_purchase_order", transaction_date=transaction_date, submit=sbool(submit))


@frappe.whitelist()
def get_settings():
	settings = frappe.get_single("OCR Settings")
	return {
		"reconcile_with_purchase_receipts": settings.reconcile_with_purchase_receipts # type: ignore
	}


@frappe.whitelist()
def make_purchase_invoice_from_pr(source_name, target_doc=None, args=None): # TODO: find a better way to handle this in ERPNext directly
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import get_returned_qty_map, get_invoiced_qty_map

	if args is None:
		args = {}
	if isinstance(args, str):
		args = json.loads(args)

	from erpnext.accounts.party import get_payment_terms_template

	doc = frappe.get_doc("Purchase Receipt", source_name)
	returned_qty_map = get_returned_qty_map(source_name)
	invoiced_qty_map = get_invoiced_qty_map(source_name)

	def set_missing_values(source, target):
		if len(target.get("items")) == 0:
			frappe.throw(_("All items have already been Invoiced/Returned"))

		doc: SalesInvoice = frappe.get_doc(target) # type: ignore
		doc.payment_terms_template = get_payment_terms_template(source.supplier, "Supplier", source.company)
		doc.run_method("onload")
		doc.run_method("set_missing_values")

		if args and args.get("merge_taxes"):
			merge_taxes(source.get("taxes") or [], doc)

		doc.run_method("calculate_taxes_and_totals")
		doc.set_payment_schedule()

	def update_item(source_doc, target_doc, source_parent):
		target_doc.qty, returned_qty = get_pending_qty(source_doc)
		if frappe.db.get_single_value("Buying Settings", "bill_for_rejected_quantity_in_purchase_invoice"):
			target_doc.rejected_qty = 0
		target_doc.stock_qty = flt(target_doc.qty) * flt(
			target_doc.conversion_factor, target_doc.precision("conversion_factor")
		)
		returned_qty_map[source_doc.name] = returned_qty

	def get_pending_qty(item_row):
		qty = item_row.qty
		if frappe.db.get_single_value("Buying Settings", "bill_for_rejected_quantity_in_purchase_invoice"):
			qty = item_row.received_qty

		pending_qty = qty - invoiced_qty_map.get(item_row.name, 0)

		if frappe.db.get_single_value("Buying Settings", "bill_for_rejected_quantity_in_purchase_invoice"):
			return pending_qty, 0

		returned_qty = flt(returned_qty_map.get(item_row.name, 0))
		if item_row.rejected_qty and returned_qty:
			returned_qty -= item_row.rejected_qty

		if returned_qty:
			if returned_qty >= pending_qty:
				pending_qty = 0
				returned_qty -= pending_qty
			else:
				pending_qty -= returned_qty
				returned_qty = 0

		if qty == 1 and item_row.billed_amt <= item_row.net_amount: # @dokos: allow creating invoices based on the billed_amt
			pending_qty = 1

		return pending_qty, returned_qty

	def select_item(d):
		filtered_items = args.get("filtered_children", [])
		child_filter = d.name in filtered_items if filtered_items else True
		return child_filter

	doclist = get_mapped_doc(
		"Purchase Receipt",
		source_name,
		{
			"Purchase Receipt": {
				"doctype": "Purchase Invoice",
				"field_map": {
					"supplier_warehouse": "supplier_warehouse",
					"is_return": "is_return",
					"bill_date": "bill_date",
				},
				"validation": {
					"docstatus": ["=", 1],
				},
			},
			"Purchase Receipt Item": {
				"doctype": "Purchase Invoice Item",
				"field_map": {
					"name": "pr_detail",
					"parent": "purchase_receipt",
					"qty": "received_qty",
					"purchase_order_item": "po_detail",
					"purchase_order": "purchase_order",
					"is_fixed_asset": "is_fixed_asset",
					"asset_location": "asset_location",
					"asset_category": "asset_category",
					"wip_composite_asset": "wip_composite_asset",
				},
				"postprocess": update_item,
				"filter": lambda d: (
					get_pending_qty(d)[0] <= 0 if not doc.get("is_return") else get_pending_qty(d)[0] > 0
				),
				"condition": select_item,
			},
			"Purchase Taxes and Charges": {
				"doctype": "Purchase Taxes and Charges",
				"reset_value": not (args and args.get("merge_taxes")),
				"ignore": args.get("merge_taxes") if args else 0,
			},
		},
		target_doc,
		set_missing_values,
	)

	return doclist