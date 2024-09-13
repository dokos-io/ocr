# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

import re
import time
import difflib
import datetime
from dateutil.parser import parse

import frappe
from frappe import _
from frappe.utils import now_datetime, time_diff, flt, getdate, get_datetime, nowdate
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.model import data_fieldtypes
from pypika.terms import ExistsCriterion
from frappe.query_builder import Order

from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
from erpnext.accounts.party import get_due_date
from erpnext import get_default_company

from ocr.ocr.doctype.ocr_request.aws_textract import AWSTextractExpense
from ocr.utils import parse_number, time_diff_in_minutes

# https://docs.python.org/3/library/re.html#simulating-scanf
FLOAT_PATTERN = re.compile(r"[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?")

PURCHASE_INVOICE_MAPPING = {
	"INVOICE_RECEIPT_ID": "bill_no",
	"INVOICE_RECEIPT_DATE": "bill_date",
	"VENDOR_NAME": "supplier",
	"RECEIVER_NAME": "company",
	"TAX_PAYER_ID": "tax_id",
	"DUE_DATE": "due_date"
}

GRAND_TOTAL_KEY = "TOTAL"
TAX_TOTAL_KEY = "TAX"

class OCRRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from ocr.ocr.doctype.ocr_header_mapping.ocr_header_mapping import OCRHeaderMapping
		from ocr.ocr.doctype.ocr_line_items_mapping.ocr_line_items_mapping import OCRLineItemsMapping

		analysis: DF.Code | None
		bill_date: DF.Date | None
		bill_no: DF.Data | None
		company: DF.Link | None
		due_date: DF.Date | None
		error: DF.SmallText | None
		file: DF.Link | None
		filename: DF.Data | None
		grand_total: DF.Float
		header_mapping: DF.Table[OCRHeaderMapping]
		job: DF.SmallText | None
		line_items_mapping: DF.Table[OCRLineItemsMapping]
		net_total: DF.Float
		ocr_basket: DF.Link | None
		status: DF.Literal["Pending", "Analysis Completed", "Purchase Order Created", "Purchase Invoice Created", "Error", "Closed", "Completed"]
		supplier: DF.Link | None
		tax_total: DF.Float
		transaction_type: DF.Literal["", "Purchase Invoice", "Expense"]
	# end: auto-generated types

	def before_insert(self):
		# Keep to avoid auto fill from default values
		self.company = None
		self.supplier = None

	def after_insert(self):
		frappe.enqueue_doc(
			self.doctype,
			self.name,
			"make_analysis",
			queue="long",
			enqueue_after_commit=True,
			now=frappe.flags.in_test,
		)

	def validate(self):
		# TODO: Improve the logic
		for item in self.header_mapping:
			if item.key == "VENDOR_NAME":
				if self.supplier and item.field_value != self.supplier:
					item.field = "supplier"
					item.field_value = self.supplier
				elif not self.supplier and item.field_value:
					self.supplier = item.field_value

			elif item.key == "RECEIVER_NAME":
				if self.company and item.field_value != self.company:
					item.field = "company"
					item.field_value = self.company
				elif not self.company and item.field_value:
					self.company = item.field_value

		if not self.company and len(frappe.get_all("Company")) == 1:
			self.company = get_default_company()

		if self.analysis:
			self.find_header_correspondence()
			self.find_line_items_correspondence()

		self.calculate_due_date()
		self.set_status()

	@frappe.whitelist()
	def make_analysis(self):
		self.get_analysis()

	def start_analysis(self):
		textract = AWSTextractExpense(self)
		jobid = textract.task.start()
		self.job = jobid
		self.db_set("job", jobid)

	def get_analysis(self):
		if not self.job:
			self.start_analysis()

		try:
			return self.get_textract_analysis()
		except Exception:
			self.log_error(_("OCR Analysis Error"))

	def get_textract_analysis(self):
		if self.analysis and frappe.parse_json(self.analysis).get("JobStatus") == "SUCCEEDED":
			return frappe.parse_json(self.analysis)

		textract = AWSTextractExpense(self)
		if analysis := textract.task.get_result():
			if analysis["JobStatus"] == "SUCCEEDED":
				self.register_parsed_data(analysis.get("ParsedData", {}))
				self.analysis = frappe.as_json(analysis)
				self.save()

			elif time_diff_in_minutes(now_datetime(), get_datetime(self.creation)) < 60:
				time.sleep(25)
				frappe.enqueue_doc(
					self.doctype,
					self.name,
					"get_analysis",
					queue="short",
				)

			elif time_diff(now_datetime(), get_datetime(self.creation)) > 7:
				self.set_and_return_error("stale")

		elif self.status != "Error":
			self.set_and_return_error("no result")

		return analysis

	def on_trash(self):
		textract = AWSTextractExpense(self)
		textract.task.delete()

	def set_status(self, commit=False):
		if self.status == "Closed":
			return

		status = "Pending"
		if self.job:
			status = "Analysis Completed"
		if frappe.db.exists("Purchase Order", dict(ocr_request=self.name)):
			status = "Purchase Order Created"
		if frappe.db.exists("Purchase Invoice", dict(ocr_request=self.name)):
			status = "Purchase Invoice Created"
		if frappe.db.exists("Purchase Invoice", dict(ocr_request=self.name, docstatus=1)):
			status = "Completed"
		if self.error:
			status = "Error"

		self.status = status
		if commit:
			self.db_set("status", status)

	def reset_status_and_error(self):
		self.db_set("error", "")
		self.set_status(True)

	def set_and_return_error(self, msg):
		frappe.db.rollback()
		self.db_set("status", "Error")
		self.db_set("error", msg)
		return {
			"status": "Error",
			"message": msg
		}

	@frappe.whitelist()
	def link_to_sales_order(self, order):
		if frappe.db.exists("Purchase Order", order):
			frappe.db.set_value("Purchase Order", order, "ocr_request", self.name)
			frappe.db.set_value("Purchase Order", order, "ocr_original_file", self.file)


	@frappe.whitelist()
	def create_purchase_documents(self, order=None):
		self.reset_status_and_error()

		filters = dict(ocr_request=self.name, docstatus=1) if not order else dict(name=order)
		self.purchase_orders = frappe.get_all("Purchase Order", filters=filters)
		settings = frappe.get_single("OCR Settings")

		self.link_to_company()
		self.link_to_supplier()

		if self.status not in ["Purchase Invoice Created", "Completed"]:
			if not self.purchase_orders:
				self.purchase_orders = self.get_matched_orders()

			if not self.purchase_orders:
				if settings.auto_create_purchase_orders:
					if not frappe.db.exists("Purchase Order", {"ocr_request": self.name, "docstatus": 0}):
						self.create_purchase_order()
				else:
					return self.set_and_return_error(_("No matching order found"))

		if self.purchase_orders and not settings.do_not_create_purchase_invoices:
			if purchase_invoice := self.create_purchase_invoice():
				return self.insert_purchase_invoice(purchase_invoice, settings.auto_submit_purchase_invoices)

	def link_to_company(self):
		if self.company:
			return

		self.company = self.get_company()

	def link_to_supplier(self):
		if self.supplier:
			return

		self.supplier = self.get_supplier_name()

	def check_transaction_master_data(self):
		if not self.company:
			return self.set_and_return_error(_("Please select a company"))

		if not self.supplier:
			return self.set_and_return_error(_("Please select a supplier"))

	def create_purchase_order(self):
		if self.check_transaction_master_data():
			return

		try:
			purchase_order = make_purchase_order(self.name)
			purchase_order.flags.ignore_mandatory = True
			purchase_order.flags.ignore_validate = True
			purchase_order.title = purchase_order.supplier_name or frappe.db.get_value("Supplier", purchase_order.supplier, "supplier_name")
			purchase_order.insert()
			self.set_status()

			return purchase_order

		except Exception as e:
			return self.set_and_return_error(str(e))

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
			for child in self.line_items_mapping:
				for open_order in open_orders:
					if re.search(r"(?<![\w\d])" + re.escape(open_order.name) + r"(?![\w\d])", child.get("expense_row") or "", re.IGNORECASE):
						matched_orders.add(open_order.name)
					elif re.search(r"(?<![\w\d])" + re.escape(open_order.order_confirmation_no or "") + r"(?![\w\d])", child.get("expense_row") or "", re.IGNORECASE):
						matched_orders.add(open_order.name)
		elif open_orders:
			if closest_order := min(open_orders, key=lambda x:abs(x.net_total - self.net_total)):
				matched_orders.add(closest_order.name)

		return matched_orders

	def create_purchase_invoice(self):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

		if self.check_transaction_master_data():
			return

		purchase_invoice = None
		for matched_order in self.purchase_orders:
			if purchase_invoice:
				for item in make_purchase_invoice(matched_order).get("items"):
					purchase_invoice.append("items", item)
			else:
				purchase_invoice = make_purchase_invoice(matched_order)

		return purchase_invoice

	def insert_purchase_invoice(self, purchase_invoice, submit=True):
		if purchase_invoice and isinstance(purchase_invoice, Document):
			for key, value in self.get_header_parsed_dict().items():
				if value:
					purchase_invoice.update({key: value})

			purchase_invoice.ocr_request = self.name
			purchase_invoice.set_posting_time = True
			purchase_invoice.flags.ignore_mandatory = True
			purchase_invoice.flags.ignore_validate = True

			purchase_invoice.run_method("set_missing_values")
			purchase_invoice.run_method("calculate_taxes_and_totals")
			purchase_invoice.title = purchase_invoice.supplier_name or frappe.db.get_value("Supplier", purchase_invoice.supplier, "supplier_name")
			purchase_invoice.insert()

			if submit:
				purchase_invoice.submit()

			return purchase_invoice.name

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

	def register_parsed_data(self, parsed_data):
		self.header_mapping = []
		self.line_items_mapping = []
		for key, value in parsed_data.items():
			if key == "_children":
				for child in parsed_data["_children"]:
					row = {}
					for row_key, row_value in child.items():
						if row_key in ["QUANTITY", "UNIT_PRICE", "PRICE"]:
							row[row_key.lower()] = parse_number(row_value)
						else:
							row[row_key.lower()] = row_value
					self.append("line_items_mapping", row)
			else:
				self.append("header_mapping", {
					"key": key,
					"value": value
				})

			if key == GRAND_TOTAL_KEY:
				self.grand_total = parse_number(value)

			if key == TAX_TOTAL_KEY:
				self.tax_total = parse_number(value)

		self.net_total = flt(self.grand_total) - flt(self.tax_total)

	def get_header_dict(self):
		return {line.key: line.value for line in self.header_mapping}

	def get_header_parsed_dict(self):
		parsed_dict = {}
		for line in self.header_mapping:
			if line.field and line.field != "supplier":
				value = line.field_value or line.value
				if "date" in line.field and not (isinstance(value, datetime.datetime) or isinstance(value, datetime.date)):
					try:
						parsed_dict[line.field] = getdate(line.field_value)
					except Exception:
						parsed_dict[line.field] = None
				else:
					parsed_dict[line.field] = line.field_value or line.value
		return parsed_dict

	def find_header_correspondence(self):
		pi_fields = [f.fieldname for f in frappe.get_meta("Purchase Invoice").fields]

		for line in self.header_mapping:
			predefined_mapping = PURCHASE_INVOICE_MAPPING.get(line.key)

			if line.field_value:
				if predefined_mapping and hasattr(self, predefined_mapping):
					if not self.get(predefined_mapping):
						self.set(predefined_mapping, line.field_value)
				continue

			if line.key.lower() in pi_fields:
				line.field = (line.key.lower() or "")[:140]
			elif predefined_mapping:
				line.field = (predefined_mapping or "")[:140]

			if line.key == "VENDOR_NAME":
				line.field_value = self.get_supplier_name()

			elif line.key == "RECEIVER_NAME":
				line.field_value = self.get_company()

			elif "DATE" in line.key:
				try:
					line.field_value = getdate(parse(line.value))
				except Exception:
					pass

			elif line.field:
				line.field_value = line.value

	def find_line_items_correspondence(self):
		for line in self.line_items_mapping:
			if line.item_code:
				continue

			line.item_code = self.get_supplier_item(line.get("item")) or self.get_previous_correspondance(line.get("item"))

	def get_supplier_name(self):
		header = self.get_header_dict()
		supplier = None
		if header.get("VENDOR_VAT_NUMBER"):
			supplier = frappe.db.get_value("Supplier", dict(tax_id=header.get("VENDOR_VAT_NUMBER")))

		if not supplier and header.get("VENDOR_NAME"):
			supplier = frappe.db.get_value("Supplier", header.get("VENDOR_NAME"))

			if not supplier:
				supplier = self.get_value_from_mapping("VENDOR_NAME", header.get("VENDOR_NAME"), "supplier")

		if not supplier and header.get("VENDOR_NAME") and len(header.get("VENDOR_NAME").split(" ")) > 1:
			for substring in header.get("VENDOR_NAME").split(" "):
				if supplier := frappe.db.get_value("Supplier", substring):
					break

		if not supplier and header.get("VENDOR_NAME"):
			existing_suppliers = frappe.get_all("Supplier", filters=dict(disabled=0), fields=["name", "supplier_name"])
			existing_supplier_dict = {supplier.supplier_name: supplier.name for supplier in existing_suppliers}

			if existing_supplier_list := [supplier.supplier_name for supplier in existing_suppliers]:
				best_match = next(iter(sorted(
					existing_supplier_list,
					key=lambda doc: difflib.SequenceMatcher(
						lambda doc: doc == " ", doc.lower(), header.get("VENDOR_NAME", "").lower()
					).ratio(),
					reverse=True,
				)))

				if difflib.SequenceMatcher(lambda doc: doc == " ", best_match.lower(), header.get("VENDOR_NAME", "").lower()).ratio() > 0.9:
					supplier = existing_supplier_dict.get(best_match)

		self.supplier = supplier if (supplier and frappe.db.exists("Supplier", supplier)) else None

		return supplier or ""

	def get_company(self):
		header = self.get_header_dict()
		company = None

		company = self.get_value_from_mapping("RECEIVER_NAME", header.get("RECEIVER_NAME"), "company")

		companies = [x.lower() for x in frappe.get_all("Company", pluck="name")]
		if company_match := difflib.get_close_matches(header.get("RECEIVER_NAME","").lower(), companies, cutoff=0.9):
			company = company_match[0]

		if not company and (company_match := difflib.get_close_matches(header.get("RECEIVER_ADDRESS", "").lower(), companies, cutoff=0.9)):
			company = company_match[0]

		if not company:
			for company_name in companies:
				if company_name in header.get("RECEIVER_NAME", "").lower() or company_name in header.get("RECEIVER_ADDRESS", "").lower():
					company = company_name

		if not company and len(companies) == 1:
			company = companies[0]

		self.company = company
		return company or ""

	def get_value_from_mapping(self, key, value, field):
		return frappe.db.get_value(
			"OCR Header Mapping",
			dict(
				key=key,
				value=value,
				field=field,
				parent=("!=", self.name)
			),
			"field_value",
		)

	def get_supplier_item(self, item):
		if not self.supplier:
			return

		return frappe.db.get_value(
			"Item Supplier",
			dict(
				supplier=self.supplier,
				supplier_part_no=item
			),
			"parent"
		)

	def get_previous_correspondance(self, item):
		if not self.company or not self.supplier:
			return

		ocr_request = frappe.qb.DocType("OCR Request")
		ocr_request_line_mapping = frappe.qb.DocType("OCR Line Items Mapping")

		query = (
			frappe.qb.from_(ocr_request)
			.left_join(ocr_request_line_mapping)
			.on(ocr_request.name == ocr_request_line_mapping.parent)
			.select(ocr_request_line_mapping.item_code, ocr_request.name)
			.where(ocr_request.company == self.company)
			.where(ocr_request.supplier == self.supplier)
			.where(ocr_request_line_mapping.item == item)
			.where(ocr_request_line_mapping.item_code.isnotnull())
			.orderby(ocr_request.modified, order=Order.desc)
		)
		if result := query.run(as_dict=True):
			return result[0].item_code

	def get_purchase_invoice_qty(self, row):
		if row.get("unit_price") and row.get("price") and row.get("price") != row.get("unit_price"):
			return flt(row.get("price") ) / flt(row.get("unit_price"))

		elif row.get("quantity"):
			return row.get("quantity")

		return 1

	def get_purchase_invoice_uom(self, row):
		expense_row = row.get("EXPENSE_ROW")

		if expense_row and (before_unit_price := re.search(r".+?(?=" + re.escape(row.get("unit_price")) + r")", expense_row, re.IGNORECASE)):
			for section in reversed(before_unit_price[0].strip().split()):
				if not section.isnumeric() and frappe.db.get_value("UOM", section):
					return section

		return frappe.db.get_single_value("Stock Settings", "stock_uom")

	@frappe.whitelist()
	def close_request(self):
		self.db_set("status", "Closed")

	@frappe.whitelist()
	def open_request(self):
		self.status = "Pending"
		self.set_status(True)

	@frappe.whitelist()
	def register_mapping(self, data):
		data = frappe.parse_json(data)

		if data.get("supplier"):
			self.db_set("supplier", data.get("supplier"))

		for row in data.get("items", []):
			for mapping_row in self.line_items_mapping:
				if row.get("item_code") and mapping_row.item == row.get("item_name"):
					frappe.db.set_value(mapping_row.doctype, mapping_row.name, "item_code", row.get("item_code"))

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

def check_pending_analysis():
	for req in frappe.get_all("OCR Request", filters={"status": "Pending"}, limit=500):
		doc = frappe.get_doc("OCR Request", req.name)
		doc.run_method("get_analysis")

@frappe.whitelist()
def get_analysis(request_id):
	doc = frappe.get_doc("OCR Request", request_id)
	return doc.get_analysis()

@frappe.whitelist()
def make_purchase_order(source_name, target_doc=None):
	def set_missing_values(source, target):
		if target.supplier:
			target.currency = (
				frappe.db.get_value("Supplier", target.supplier, "default_currency") or
				frappe.get_cached_value("Company", target.company, "default_currency")
			)

		header = source.get_header_parsed_dict()
		if header.get("bill_date"):
			target.transaction_date = header.get("bill_date")
			target.schedule_date = header.get("bill_date")

		generic_item = frappe.db.get_single_value("OCR Settings", "generic_item")
		if source.get_creation_mode() == "Consolidate all rows in a single invoicing line":
			target.items = []
			target.append("items", {
				"item_code": generic_item,
				"description": _("Invoice Net Total"),
				"qty": 1,
				"rate": source.net_total,
			})

			if target.taxes:
				target.taxes[0].charge_type = "Actual"
				target.taxes[0].tax_amount = source.tax_total

		target.ocr_request = source.name

		target.run_method("set_missing_values")
		target.run_method("get_schedule_dates")
		target.run_method("calculate_taxes_and_totals")

	def update_item(source, target, source_parent):
		target.qty = source.quantity or 1
		target.rate = source.unit_price if target.qty > 1 and source.unit_price else source.price
		if source.item:
			target.item_name = source.item[:140]
		target.description = source.expense_row

	doclist = get_mapped_doc(
		"OCR Request",
		source_name,
		{
			"OCR Request": {
				"doctype": "Purchase Order",
				"field_no_map": ["status"],
			},
			"OCR Line Items Mapping": {
				"doctype": "Purchase Order Item",
				"field_map": [
					["quantity", "qty"],
					["unit_price", "rate"],
					["item", "item_name"],
					["expense_row", "description"],
					["name", "ocr_request_line_item"]
				],
				"postprocess": update_item,
				"condition": lambda doc: doc.quantity or doc.unit_price or doc.price,
			},
		},
		target_doc,
		set_missing_values,
	)

	return doclist


def on_purchase_order_update(doc, method):
	if not doc.ocr_request:
		return

	for item in doc.items:
		if item.item_code and item.ocr_request_line_item:
			if frappe.db.get_value("OCR Line Items Mapping", item.ocr_request_line_item, "item_code") != item.item_code:
				frappe.db.set_value("OCR Line Items Mapping", item.ocr_request_line_item, "item_code", item.item_code, update_modified=False)

	ocr_request = frappe.db.get_value("OCR Request", doc.ocr_request, ["company", "supplier"], as_dict=True)
	if ocr_request.company != doc.company:
		frappe.db.set_value("OCR Request", doc.ocr_request, "company", doc.company, update_modified=False)
	if ocr_request.supplier != doc.supplier:
		frappe.db.set_value("OCR Request", doc.ocr_request, "supplier", doc.supplier, update_modified=False)


def on_purchase_order_submission(doc, method):
	if doc.ocr_request:
		ocr_request = frappe.get_doc("OCR Request", doc.ocr_request)
		ocr_request.create_purchase_documents(doc.name)


def update_ocr_request_status(doc, method):
	if doc.ocr_request:
		ocr_request = frappe.get_doc("OCR Request", doc.ocr_request)
		ocr_request.set_status(True)

def map_ocr_data(doc, method=None, source_doc=None):
	if doc.ocr_request:
		for field in ["company", "supplier", "bill_no", "bill_date", "due_date"] + get_custom_fields():
			if not doc.get(field):
				doc.set(
					field,
					frappe.db.get_value("OCR Request", doc.ocr_request, field)
				)


def get_custom_fields():
	return frappe.get_all("Custom Field", filters={"dt": "OCR Request", "fieldtype": ("in", data_fieldtypes)}, pluck="fieldname")