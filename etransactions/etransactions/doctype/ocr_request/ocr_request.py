# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

import re
import time
import difflib

import frappe
from frappe import _
from frappe.utils import now_datetime, time_diff_in_hours, get_datetime
from frappe.model.document import Document

from etransactions.etransactions.doctype.ocr_request.aws_textract import AWSTextractExpense
from etransactions.etransactions.doctype.ocr_request.mistral_ocr import MistralOCR
from etransactions.utils import parse_number, date_parser

# https://docs.python.org/3/library/re.html#simulating-scanf
FLOAT_PATTERN = re.compile(r"[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?")

PURCHASE_INVOICE_MAPPING = {
	"INVOICE_RECEIPT_ID": "bill_no",
	"INVOICE_RECEIPT_DATE": "bill_date",
	"VENDOR_NAME": "supplier",
	"RECEIVER_NAME": "company",
	"TAX_PAYER_ID": "tax_id",
	"VENDOR_VAT_NUMBER": "tax_id",
	"DUE_DATE": "due_date",
	"VENDOR_ADDRESS": "vendor_address"
}

PURCHASE_INVOICE_TOTALS = dict(
	TOTAL = "grand_total",
	TAX = "tax_total",
	SUBTOTAL = "net_total",
)

class OCRRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		analysis: DF.Code | None
		error: DF.SmallText | None
		file: DF.Link | None
		filename: DF.Data | None
		job: DF.SmallText | None
		ocr_basket: DF.Link | None
		status: DF.Literal["Pending", "Analysis Completed", "Error", "Closed", "Completed"]
		transaction_type: DF.Literal["", "Purchase Invoice", "Expense"]
	# end: auto-generated types

	def after_insert(self):
		frappe.enqueue_doc(
			self.doctype,
			self.name,
			"make_analysis",
			queue="long",
			enqueue_after_commit=True,
			now=frappe.flags.in_test,
		)

	def before_save(self):
		if self.job and self.analysis:
			if self.transaction_type == "Purchase Invoice" and not frappe.db.get_value("Pending Purchase Invoice", dict(ocr_request=self.name)):
				self.create_pending_purchase_invoice()

	@frappe.whitelist()
	def make_analysis(self):
		self.get_analysis()

	def start_ocr_analysis(self):
		ocr_service = frappe.db.get_single_value("eTransactions Settings", "ocr_service")
		if ocr_service == "Mistral eTransactions":
			return self.start_mistral_analysis()
		else:
			return self.start_textract_analysis()

	def start_textract_analysis(self):
		textract = AWSTextractExpense(self)
		jobid = textract.task.start()
		self.job = jobid
		self.db_set("job", jobid)

	def start_mistral_analysis(self):
		mistral = MistralOCR(self)

		jobid = mistral.upload_file()
		self.job = jobid
		self.db_set("job", jobid)

	def get_analysis(self):
		if not self.file:
			self.set_and_return_error("no file")

		if not self.job:
			self.start_ocr_analysis()

		try:
			return self.get_ocr_analysis()
		except Exception:
			self.log_error(_("eTransactions Analysis Error"))

	def get_ocr_analysis(self):
		if self.analysis:
			return self.get_raw_data()

		ocr_service = frappe.db.get_single_value("eTransactions Settings", "ocr_service")
		if ocr_service == "Mistral eTransactions":
			return self.get_mistral_analysis()
		else:
			return self.get_textract_analysis()

	def get_textract_analysis(self):
		textract = AWSTextractExpense(self)
		if analysis := textract.task.get_result():
			if analysis["JobStatus"] == "SUCCEEDED":
				self.analysis = frappe.as_json(analysis.get("ParsedData", {}))
				self.save()
				self.delete_remote_file()

			elif time_diff_in_hours(now_datetime(), get_datetime(self.creation)) < (7 * 24) : # Check for 7 days
				time.sleep(25)
				frappe.enqueue_doc(
					self.doctype,
					self.name,
					"get_analysis",
					queue="short",
				)

			elif time_diff_in_hours(now_datetime(), get_datetime(self.creation)) > (7 * 24):
				self.set_and_return_error("stale")

		elif self.status != "Error":
			self.set_and_return_error("no result")

		return analysis

	def get_mistral_analysis(self):
		if not self.job:
			return

		mistral = MistralOCR(self)

		signed_url = mistral.get_signed_url(self.job)
		results = mistral.get_ocr_results(signed_url.url)
		self.analysis = frappe.as_json(results)

		self.save()
		self.delete_remote_file()

	def delete_remote_file(self, log_exception = True):
		try:
			ocr_service = frappe.db.get_single_value("eTransactions Settings", "ocr_service")
			if ocr_service == "Mistral eTransactions":
				if self.job:
					mistral = MistralOCR(self)
					mistral.delete_file(self.job)
			else:
				textract = AWSTextractExpense(self)
				textract.task.delete()
		except Exception:
			if log_exception:
				frappe.log_error(_("eTransactions File Deletion Error"))

	def on_trash(self):
		self.delete_remote_file()

	def set_status(self, commit=False):
		if self.status == "Closed":
			return

		status = "Pending"
		if ppi_status := frappe.db.get_value("Pending Purchase Invoice", dict(ocr_request=self.name)):
			if ppi_status in ["Closed", "Completed"]:
				status = ppi_status
		if self.job:
			status = "Analysis Completed"
		if self.error:
			status = "Error"

		self.status = status
		if commit:
			self.db_set("status", status)

		self.update_parent_status()

	def update_parent_status(self):
		if self.ocr_basket:
			frappe.get_doc("Supplier Invoices Basket", self.ocr_basket).run_method("set_status")

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

	def get_supplier_name(self):
		header = self.get_raw_data()
		supplier = None
		if header.get("VENDOR_VAT_NUMBER"):
			supplier = frappe.db.get_value("Supplier", dict(tax_id=header.get("VENDOR_VAT_NUMBER")))

		if not supplier and header.get("TAX_PAYER_ID"):
			supplier = frappe.db.get_value("Supplier", dict(tax_id=header.get("TAX_PAYER_ID")))

		if not supplier and header.get("VENDOR_NAME"):
			supplier = frappe.db.get_value("Supplier", header.get("VENDOR_NAME"))

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
		header = self.get_raw_data()
		company = None
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

	@frappe.whitelist()
	def close_request(self):
		self.db_set("status", "Closed")

	@frappe.whitelist()
	def open_request(self):
		self.status = "Pending"
		self.set_status(True)

	def get_raw_data(self):
		return frappe.parse_json(self.analysis or {})

	def get_data_from_analysis(self):
		return self.get_parsed_data()

	def get_parsed_data(self):
		data = {}
		items = []
		parsed_data = self.get_raw_data()
		for key, value in parsed_data.items():
			if key == "_children":
				for child in parsed_data["_children"]:
					row = {}
					for row_key, row_value in child.items():
						if row_key in ["QUANTITY", "UNIT_PRICE", "PRICE"]:
							row[row_key.lower()] = parse_number(row_value)
						else:
							row[row_key.lower()] = row_value
					items.append(row)
			else:
				fieldname, fieldvalue = self.find_header_correspondence(key, value)
				if fieldname and fieldvalue:
					data[fieldname] = fieldvalue

		data["items"] = items
		return data

	def find_header_correspondence(self, key, value):
		pi_fields = [f.fieldname for f in frappe.get_meta("Purchase Invoice").fields]
		locale = frappe.db.get_single_value("System Settings", "language")

		fieldname = None
		if key in PURCHASE_INVOICE_MAPPING:
			fieldname = PURCHASE_INVOICE_MAPPING.get(key)[:140]
		elif key.lower() in pi_fields:
			fieldname = (key.lower() or "")[:140]

		match key:
			case "VENDOR_NAME":
				return "supplier", self.get_supplier_name()
			case "RECEIVER_NAME":
				return "company", self.get_company()
			case key if key in PURCHASE_INVOICE_TOTALS.keys():
				return PURCHASE_INVOICE_TOTALS[key], parse_number(value)
			case key if "DATE" in key and fieldname:
				try:
					return fieldname, date_parser(value, locale=locale)
				except Exception:
					return None, None
			case _:
				return fieldname or key, value


	def create_pending_purchase_invoice(self):
		data = self.get_data_from_analysis()

		doc = frappe.new_doc("Pending Purchase Invoice")
		doc.company = data.get("company")
		doc.supplier = data.get("supplier")
		doc.bill_no = data.get("bill_no")
		doc.bill_date = data.get("bill_date")
		doc.due_date = data.get("due_date")
		doc.supplier_net_amount = data.get("net_total")
		doc.supplier_tax_amount = data.get("tax_total")
		doc.supplier_grand_total = data.get("grand_total")
		doc.ocr_request = self.name
		doc.file = self.file
		doc.vendor_address = data.get("vendor_address")
		doc.tax_id = data.get("tax_id")
		doc.ocr_basket = self.ocr_basket

		return doc.insert(ignore_mandatory=True, ignore_links=True)


def check_pending_analysis():
	for req in frappe.get_all("OCR Request", filters={"status": ("in", ["Pending", "Error"])}, limit=500):
		try:
			doc = frappe.get_doc("OCR Request", req.name)
			doc.run_method("get_analysis")
			doc.run_method("set_status", commit=True)
		except Exception:
			doc.log_error()
			continue


@frappe.whitelist()
def get_analysis(request_id):
	doc = frappe.get_doc("OCR Request", request_id)
	return doc.get_analysis()


def update_ocr_request_status(doc, method):
	if doc.ocr_request:
		ocr_request = frappe.get_doc("OCR Request", doc.ocr_request)
		ocr_request.set_status(True)
