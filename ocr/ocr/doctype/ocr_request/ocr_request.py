# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

import re
import time
import difflib
import datetime
from dateutil.parser import parse

import frappe
from frappe import _
from frappe.utils import time_diff_in_minutes, now_datetime, time_diff, flt
from frappe.model.document import Document
from pypika.terms import ExistsCriterion


from ocr.ocr.doctype.ocr_request.aws_textract import AWSTextract
from ocr.ocr.doctype.ocr_request.taggun import Taggun

# https://docs.python.org/3/library/re.html#simulating-scanf
FLOAT_PATTERN = re.compile(r"[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?")

PURCHASE_INVOICE_MAPPING = {
	"INVOICE_RECEIPT_ID": "bill_no",
	"INVOICE_RECEIPT_DATE": "bill_date",
	"VENDOR_NAME": "supplier",
	"RECEIVER_NAME": "company"
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
		if not self.company:
			error_msg = _("Please select a company in order to generate a purchase invoice")
			self.db_set("status", "Error")
			self.db_set("error", error_msg)
			return {
				"status": "error",
				"message": error_msg
			}

		purchase_invoice = None
		try:
			if self.get_creation_mode() != "Get items from the OCR analysis":
				purchase_invoice = self.make_purchase_invoice_from_purchase_order()
				frappe.log_error("err", purchase_invoice)
				if purchase_invoice.get("status") == "Error":
					self.db_set("status", "Error")
					self.db_set("error", purchase_invoice.get("message"))
					return purchase_invoice

			elif not self.supplier:
				error_msg = _("Please select a supplier in order to generate a purchase invoice")
				self.db_set("status", "Error")
				self.db_set("error", error_msg)
				return {
					"status": "Error",
					"message": error_msg
				}

			else:
				purchase_invoice = frappe.new_doc("Purchase Invoice")
				purchase_invoice.ocr_request = self.name
				purchase_invoice.supplier = self.supplier

				generic_item = frappe.db.get_single_value("OCR Settings", "generic_item")

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

			if purchase_invoice and isinstance(purchase_invoice, Document):

				for key, value in self.get_header_parsed_dict().items():
					purchase_invoice.update({key: value})

				purchase_invoice.flags.ignore_mandatory = True
				purchase_invoice.flags.ignore_validate = True

				purchase_invoice.run_method("set_missing_values")
				purchase_invoice.run_method("calculate_taxes_and_totals")
				purchase_invoice.insert()
				self.db_set("status", "Transaction Matched")

		except Exception as e:
			self.db_set("status", "Error")
			self.db_set("error", str(e))

	def make_purchase_invoice_from_purchase_order(self):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

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
			.select(purchase_order_dt.name, purchase_order_dt.net_total)
			.where((purchase_order_dt.docstatus == 1) & (purchase_order_dt.per_billed.lt(100)))
			.where(ExistsCriterion(subquery).negate())
		)

		if self.supplier:
			query = query.where(purchase_order_dt.supplier == self.supplier)

		open_orders = query.run(as_dict=True)

		matched_orders = set()

		if self.get_creation_mode() == "Get items from purchase orders recognized by the OCR":
			for child in self.line_items_mapping:
				for order in open_orders:
					if re.search(r"(?<![\w\d])" + re.escape(order.name) + r"(?![\w\d])", child.get("expense_row") or "", re.IGNORECASE):
						matched_orders.add(order.name)
		elif open_orders:
			if closest_order := min(open_orders, key=lambda x:abs(x.net_total - self.net_total)):
				matched_orders.add(closest_order.name)

		if not matched_orders:
			return {
				"status": "Error",
				"message": _("No matching order found")
			}

		purchase_invoice = None
		for matched_order in matched_orders:
			if purchase_invoice:
				for item in make_purchase_invoice(matched_order).get("items"):
					purchase_invoice.append("items", item)
			else:
				purchase_invoice = make_purchase_invoice(matched_order)

		purchase_invoice.ocr_request = self.name
		purchase_invoice.flags.ignore_mandatory = True
		purchase_invoice.flags.ignore_validate = True
		return purchase_invoice.insert()

	def get_creation_mode(self):
		if self.get("pi_creation_mode"):
			return self.pi_creation_mode

		self.pi_creation_mode = None
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
			if line.field:
				value = line.field_value or line.value
				if (
					"date" in line.field and not (isinstance(value, datetime.datetime) or isinstance(value, datetime.date))
					or line.field == "supplier"
				):
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

			if line.key == "RECEIVER_NAME":
				line.field_value = self.get_company()

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

		self.supplier = supplier

		return supplier

	def get_company(self):
		header = self.get_header_dict()
		company = None

		company = self.get_value_from_mapping("RECEIVER_NAME", header.get("RECEIVER_NAME"), "company")

		companies = [x.lower() for x in frappe.get_all("Company", pluck="name")]
		if company_match := difflib.get_close_matches(header.get("RECEIVER_NAME").lower(), companies):
			company = company_match[0]

		self.company = company
		return company

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

		if expense_row and (before_unit_price := re.search(r".+?(?=" + re.escape(row.get("unit_price")) + r")", expense_row, re.IGNORECASE)):
			for section in reversed(before_unit_price[0].strip().split()):
				if not section.isnumeric() and frappe.db.get_value("UOM", section):
					return section

		return frappe.db.get_single_value("Stock Settings", "stock_uom")

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



def parse_number(text):
	# Borrowed from https://github.com/hayj/SystemTools/blob/master/systemtools/number.py
	"""
		Return the first number in the given text for any locale.
		TODO we actually don't take into account spaces for only
		3-digited numbers (like "1 000") so, for now, "1 0" is 10.
		TODO parse cases like "125,000.1,0.2" (125000.1).

		:example:
		>>> parseNumber("a 125,00 €")
		125
		>>> parseNumber("100.000,000")
		100000
		>>> parseNumber("100 000,000")
		100000
		>>> parseNumber("100,000,000")
		100000000
		>>> parseNumber("100 000 000")
		100000000
		>>> parseNumber("100.001 001")
		100.001
		>>> parseNumber("$.3")
		0.3
		>>> parseNumber(".003")
		0.003
		>>> parseNumber(".003 55")
		0.003
		>>> parseNumber("3 005")
		3005
		>>> parseNumber("1.190,00 €")
		1190
		>>> parseNumber("1190,00 €")
		1190
		>>> parseNumber("1,190.00 €")
		1190
		>>> parseNumber("$1190.00")
		1190
		>>> parseNumber("$1 190.99")
		1190.99
		>>> parseNumber("$-1 190.99")
		-1190.99
		>>> parseNumber("1 000 000.3")
		1000000.3
		>>> parseNumber('-151.744122')
		-151.744122
		>>> parseNumber('-1')
		-1
		>>> parseNumber("1 0002,1.2")
		10002.1
		>>> parseNumber("")

		>>> parseNumber(None)

		>>> parseNumber(1)
		1
		>>> parseNumber(1.1)
		1.1
		>>> parseNumber("rrr1,.2o")
		1
		>>> parseNumber("rrr1rrr")
		1
		>>> parseNumber("rrr ,.o")

	"""
	try:
		# First we return None if we don't have something in the text:
		if text is None:
			return None
		if isinstance(text, int) or isinstance(text, float):
			return text
		text = text.strip()
		if text == "":
			return None
		# Next we get the first "[0-9,. ]+":
		n = re.search("-?[0-9]*([,. ]?[0-9]+)+", text).group(0)
		n = n.strip()
		if not re.match(".*[0-9]+.*", text):
			return None
		# Then we cut to keep only 2 symbols:
		while " " in n and "," in n and "." in n:
			index = max(n.rfind(','), n.rfind(' '), n.rfind('.'))
			n = n[0:index]
		n = n.strip()
		# We count the number of symbols:
		symbolsCount = 0
		for current in [" ", ",", "."]:
			if current in n:
				symbolsCount += 1
		# If we don't have any symbol, we do nothing:
		if symbolsCount == 0:
			pass
		# With one symbol:
		elif symbolsCount == 1:
			# If this is a space, we just remove all:
			if " " in n:
				n = n.replace(" ", "")
			# Else we set it as a "." if one occurence, or remove it:
			else:
				theSymbol = "," if "," in n else "."
				if n.count(theSymbol) > 1:
					n = n.replace(theSymbol, "")
				else:
					n = n.replace(theSymbol, ".")
		else:
			# Now replace symbols so the right symbol is "." and all left are "":
			rightSymbolIndex = max(n.rfind(','), n.rfind(' '), n.rfind('.'))
			rightSymbol = n[rightSymbolIndex:rightSymbolIndex+1]
			if rightSymbol == " ":
				return parse_number(n.replace(" ", "_"))
			n = n.replace(rightSymbol, "R")
			leftSymbolIndex = max(n.rfind(','), n.rfind(' '), n.rfind('.'))
			leftSymbol = n[leftSymbolIndex:leftSymbolIndex+1]
			n = n.replace(leftSymbol, "L")
			n = n.replace("L", "")
			n = n.replace("R", ".")
		# And we cast the text to float or int:
		n = float(n)
		if n.is_integer():
			return int(n)
		else:
			return n
	except: pass
	return None