# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

import re
import difflib
import time
import datetime
from dateutil.parser import parse

import frappe
from frappe.utils import time_diff_in_minutes, now_datetime, time_diff, flt
from frappe.model.document import Document


from ocr.ocr.doctype.ocr_request.aws_textract import AWSTextract
from ocr.ocr.doctype.ocr_request.taggun import Taggun

# https://docs.python.org/3/library/re.html#simulating-scanf
FLOAT_PATTERN = re.compile(r"[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?")

PURCHASE_INVOICE_MAPPING = {
	"INVOICE_RECEIPT_ID": "bill_no",
	"INVOICE_RECEIPT_DATE": "bill_date",
	"VENDOR_NAME": "supplier"
}

GRAND_TOTAL_KEY = "TOTAL"
TAX_TOTAL_KEY = "TAX"

class OCRRequest(Document):
	def after_insert(self):
		frappe.enqueue_doc(
			self.doctype,
			self.name,
			"make_analysis",
			queue="long",
			now=frappe.flags.in_test,
		)

	def make_analysis(self):
		self.start_analysis()
		self.get_analysis()

	def start_analysis(self):
		service = frappe.db.get_single_value("OCR Settings", "selected_ocr_service")
		if service == "AWS Textract":
			textract = AWSTextract(self)
			jobid = textract.start_analysis()
			self.db_set("job", jobid)

	def get_analysis(self):
		service = frappe.db.get_single_value("OCR Settings", "selected_ocr_service")
		if service == "AWS Textract":
			return self.get_textract_analysis()
		elif service == "Taggun":
			self.get_taggun_analysis()

	def get_textract_analysis(self):
		if self.analysis and frappe.parse_json(self.analysis).get("JobStatus") == "SUCCEEDED":
			return frappe.parse_json(self.analysis)

		textract = AWSTextract(self)
		if analysis := textract.get_analysis():
			if analysis["JobStatus"] == "SUCCEEDED":
				self.register_parsed_data(analysis.get("ParsedData", {}))
				self.find_header_correspondence()
				self.find_line_items_correspondence()
				self.analysis = frappe.as_json(analysis)
				self.status = "Analysis Completed"
				self.save()

			elif time_diff_in_minutes(now_datetime(), self.creation) < 60:
				time.sleep(25)
				frappe.enqueue_doc(
					self.doctype,
					self.name,
					"get_analysis",
					queue="short"
				)

			elif time_diff(now_datetime(), self.creation) > 7:
				self.db_set("status", "Error")

		elif self.status != "Error":
			self.db_set("status", "Error")

		return analysis

	def get_taggun_analysis(self):
		taggun = Taggun(self)
		return taggun.start_analysis()

	def on_trash(self):
		service = frappe.db.get_single_value("OCR Settings", "selected_ocr_service")
		if service == "AWS Textract":
			textract = AWSTextract(self)
			textract.delete_file()

	@frappe.whitelist()
	def create_purchase_invoice(self):
		purchase_invoice = frappe.new_doc("Purchase Invoice")
		purchase_invoice.ocr_request = self.name

		generic_item = frappe.db.get_single_value("OCR Settings", "generic_item")

		for key, value in self.get_header_parsed_dict().items():
			purchase_invoice.update({key: value})

		for child in self.line_items_mapping:
			if not child.get("item"):
				continue

			purchase_invoice.append("items", {
				"item_code": child.get("item_code") or generic_item,
				"item_name": str(child.get("item"))[:140],
				"description": child.get("expense_row") or child.get("item"),
				"qty": self.get_purchase_invoice_qty(child),
				"uom": self.get_purchase_invoice_uom(child),
				"rate": child.get("unit_price") or (child.get("quantity") == 1 and child.get("price")),
				"description": child.get("expense_row") or child.get("item")
			})

		purchase_invoice.flags.ignore_mandatory = True
		purchase_invoice.flags.ignore_validate = True

		try:
			purchase_invoice.run_method("set_missing_values")
			purchase_invoice.run_method("calculate_taxes_and_totals")
			purchase_invoice.insert()
			self.db_set("status", "Transaction Created")
		except Exception as e:
			self.db_set("status", "Error")
			self.db_set("error", str(e))

	def register_parsed_data(self, parsed_data):
		self.header_mapping = []
		self.line_items_mapping = []
		for key, value in parsed_data.items():
			if key == "_children":
				for child in parsed_data["_children"]:
					row = {}
					for row_key, row_value in child.items():
						if row_key in ["QUANTITY", "UNIT_PRICE", "PRICE"]:
							row[row_key.lower()] = self.get_first_floats(row_value)
						else:
							row[row_key.lower()] = row_value
					self.append("line_items_mapping", row)
			else:
				self.append("header_mapping", {
					"key": key,
					"value": value
				})

			if key == GRAND_TOTAL_KEY:
				self.grand_total = self.get_first_floats(value)

			if key == TAX_TOTAL_KEY:
				self.tax_total = self.get_first_floats(value)

	def get_header_dict(self):
		return {line.key: line.value for line in self.header_mapping}

	def get_header_parsed_dict(self):
		parsed_dict = {}
		for line in self.header_mapping:
			if line.field:
				value = line.field_value or line.value
				if "date" in line.field and not (isinstance(value, datetime.datetime) or isinstance(value, datetime.date)):
					continue

				parsed_dict[line.field] = line.field_value or line.value
		return parsed_dict

	def find_header_correspondence(self):
		pi_fields = [f.fieldname for f in frappe.get_meta("Purchase Invoice").fields]

		for line in self.header_mapping:
			if line.key.lower() in pi_fields:
				line.field = line.key.lower()
			elif PURCHASE_INVOICE_MAPPING.get(line.key):
				line.field = PURCHASE_INVOICE_MAPPING.get(line.key)

			if line.key == "VENDOR_NAME":
				line.field_value = self.get_supplier_name()

			if "DATE" in line.key:
				try:
					line.field_value = parse(line.value)
				except Exception:
					pass

	def find_line_items_correspondence(self):
		header = self.get_header_parsed_dict()
		for line in self.line_items_mapping:
			if "supplier" in header and header.get("supplier"):
				line.item_code = self.get_supplier_item(header["supplier"], line.get("item"))

	def get_first_floats(self, data):
		data = data.replace(" ", "")
		if data and (matching_floats := FLOAT_PATTERN.findall(data)):
			for matching_float in matching_floats[0]:
				try:
					if matching_float:
						value = matching_float.replace(" ", "").replace(",", ".") # Temporary hack to parse floats in french invoices. To be enhanced with different number formats.
						return float(value) 
				except Exception:
					continue

		return data

	def get_supplier_name(self):
		header = self.get_header_dict()
		supplier = None
		if header.get("VENDOR_VAT_NUMBER"):
			supplier = frappe.db.get_value("Supplier", dict(tax_id=header.get("VENDOR_VAT_NUMBER")))

		if not supplier and header.get("VENDOR_NAME"):
			supplier = frappe.db.get_value("Supplier", header.get("VENDOR_NAME"))

			if not supplier:
				self.get_value_from_mapping("VENDOR_NAME", header.get("VENDOR_NAME"), "supplier")

		if not supplier and header.get("VENDOR_NAME") and len(header.get("VENDOR_NAME").split(" ")) > 1:
			for substring in header.get("VENDOR_NAME").split(" "):
				supplier = frappe.db.get_value("Supplier", substring)
				if supplier:
					break

		if not supplier and header.get("VENDOR_NAME"):
			existing_supplier_list = frappe.get_all("Supplier", filters=dict(disabled=0), pluck="supplier_name")
			sorted_suppliers = sorted(
				existing_supplier_list,
				key=lambda doc: difflib.SequenceMatcher(
					lambda doc: doc == " ", doc, header.get("VENDOR_NAME")
				).ratio(),
				reverse=True,
			)

			best_match = sorted_suppliers[0]

			if difflib.SequenceMatcher(lambda doc: doc == " ", best_match, header.get("VENDOR_NAME")).ratio() > 0.4:
				supplier = sorted_suppliers[0]

		return supplier

	def get_value_from_mapping(self, key, value, field):
		return frappe.db.get_value(
			"OCR Header Mapping",
			dict(
				key=key,
				value=value,
				field=field
			),
			"field_value"
		)


	def get_supplier_item(self, supplier, item):
		return frappe.db.get_value(
			"Item Supplier",
			dict(
				supplier=supplier,
				supplier_part_no=item
			),
			"parent"
		)

	def get_purchase_invoice_qty(self, row):
		if row.get("unit_price") and row.get("price") and row.get("price") != row.get("unit_price"):
			return flt(row.get("price") ) / flt(row.get("unit_price"))

		elif row.get("quantity"):
			return row.get("quantity")

		return 1

	def get_purchase_invoice_uom(self, row):
		expense_row = row.get("EXPENSE_ROW")

		if expense_row and (before_unit_price := re.match(r".+?(?=" + re.escape(row.get("unit_price")) + r")", expense_row, re.IGNORECASE)):
			for section in reversed(before_unit_price[0].strip().split()):
				if not section.isnumeric() and frappe.db.get_value("UOM", section):
					return section

		return frappe.db.get_single_value("OCR Settings", "default_uom")

def check_pending_analysis():
	for req in frappe.get_all("OCR Request", filters={"status": "Pending"}):
		doc = frappe.get_doc("OCR Request", req.name)
		doc.run_method("get_analysis")

@frappe.whitelist()
def get_analysis(request_id):
	doc = frappe.get_doc("OCR Request", request_id)
	return doc.get_analysis()

@frappe.whitelist()
def register_supplier_mapping(validated_data, service="AWS Textract"):
	data = frappe.parse_json(validated_data)

	for d in data:
		if d not in ["supplier", "items"]:
			continue

		if d == "supplier":
			if data.get("vendor_name") == data[d]:
				continue

			if existing_mapping := frappe.db.get_value("OCR Mapping",
				dict(
					ocr_service=service,
					key="VENDOR_NAME",
					value=data.get("vendor_name"),
					reference_doctype="Supplier"
				),
				["reference_name", "name"],
				as_dict=True
			):
				if existing_mapping.reference_name != data[d]:
					frappe.db.set_value("OCR Mapping", existing_mapping.name, "reference_name", data[d])


		if d == "items":
			for it in data[d]:
				if not frappe.db.get_value(
					"Item Supplier",
					dict(
						supplier=data["supplier"],
						supplier_part_no=it.get("item_name")
					),
				):
					item = frappe.get_doc("Item", it.get("item_code"))
					item.append("supplier_items", {
						"supplier": data["supplier"],
						"supplier_part_no": it.get("item_name")
					})
					item.flags.ignore_permissions = True
					item.save()