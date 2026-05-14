# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING

import re
import time
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime, time_diff_in_hours, get_datetime
from frappe.model.document import Document

from etransactions.etransactions.doctype.ocr_request.aws_textract import AWSTextractExpense
from etransactions.etransactions.doctype.ocr_request.mistral_ocr import MistralOCR
from etransactions.utils import parse_number, date_parser
from etransactions.controllers.entity_resolver import InvoiceEntityResolverMixin

if TYPE_CHECKING:
	from etransactions.etransactions.doctype.supplier_invoice.supplier_invoice import SupplierInvoice

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
	"VENDOR_ADDRESS": "vendor_address",
	"VENDOR_IBAN": "vendor_iban",
}

PURCHASE_INVOICE_TOTALS = dict(
	TOTAL = "grand_total",
	TAX = "tax_total",
	SUBTOTAL = "net_total",
)

class OCRRequest(Document, InvoiceEntityResolverMixin):
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

	def after_insert(self) -> None:
		frappe.enqueue_doc(
			self.doctype,
			self.name,
			"make_analysis",
			queue="long",
			enqueue_after_commit=True,
			now=frappe.in_test,
		)

	def before_save(self) -> None:
		if self.job and self.analysis:
			if self.transaction_type == "Purchase Invoice" and not frappe.db.get_value("Supplier Invoice", dict(ocr_request=self.name)):
				self.create_supplier_invoice()

	@frappe.whitelist()
	def make_analysis(self) -> None:
		self.get_analysis()

	def start_ocr_analysis(self) -> None:
		ocr_service = frappe.db.get_single_value("eTransactions Settings", "ocr_service")
		if ocr_service == "Mistral OCR":
			self.start_mistral_analysis()
		else:
			self.start_textract_analysis()

	def start_textract_analysis(self) -> None:
		textract = AWSTextractExpense(self)
		jobid = textract.task.start()
		self.job = jobid
		self.db_set("job", jobid)

	def start_mistral_analysis(self) -> None:
		mistral = MistralOCR(self)
		jobid = mistral.upload_file()
		self.job = jobid
		self.db_set("job", jobid)

	def get_analysis(self) -> dict[str, Any] | None:
		if not self.file:
			return self.set_and_return_error("no file")

		if not self.job:
			self.start_ocr_analysis()

		try:
			return self.get_ocr_analysis()
		except Exception as e:
			self.log_error(_("eTransactions Analysis Error"))
			return self.set_and_return_error(str(e))

	def get_ocr_analysis(self) -> dict[str, Any] | None:
		if self.analysis:
			return self.get_raw_data()

		ocr_service = frappe.db.get_single_value("eTransactions Settings", "ocr_service")
		if ocr_service == "Mistral OCR":
			return self.get_mistral_analysis()
		else:
			return self.get_textract_analysis()

	def get_textract_analysis(self) -> dict[str, Any] | None:
		textract = AWSTextractExpense(self)
		if analysis := textract.task.get_result():
			if analysis["JobStatus"] == "SUCCEEDED":
				self.analysis = frappe.as_json(analysis.get("ParsedData", {}))
				self.save()
				self.delete_remote_file()

			elif time_diff_in_hours(now_datetime(), get_datetime(self.creation)) < (7 * 24):  # Check for 7 days
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

	def get_mistral_analysis(self) -> None:
		if not self.job:
			return

		mistral = MistralOCR(self)

		signed_url = mistral.get_signed_url(self.job)
		results = mistral.get_ocr_results(signed_url.url)

		if not results:
			return

		self.analysis = frappe.as_json(results)

		self.save()
		self.delete_remote_file()

	def delete_remote_file(self, log_exception: bool = True) -> None:
		try:
			ocr_service = frappe.db.get_single_value("eTransactions Settings", "ocr_service")
			if ocr_service == "Mistral OCR":
				if self.job:
					mistral = MistralOCR(self)
					mistral.delete_file(self.job)
			else:
				textract = AWSTextractExpense(self)
				textract.task.delete()
		except Exception:
			if log_exception:
				frappe.log_error(_("eTransactions File Deletion Error"))

	def on_trash(self) -> None:
		self.delete_remote_file()

	def set_status(self, commit: bool = False) -> None:
		if self.status == "Closed":
			return

		status = "Pending"
		if ppi_status := frappe.db.get_value("Supplier Invoice", dict(ocr_request=self.name)):
			if ppi_status in ["Closed", "Completed"]:
				status = ppi_status
		if self.job:
			status = "Analysis Completed"
		if self.error:
			status = "Error"

		self.status = status
		if commit:
			self.db_set("status", status)

	def reset_status_and_error(self) -> None:
		self.db_set("error", "")
		self.set_status(True)

	def set_and_return_error(self, msg: str) -> dict[str, str]:
		frappe.db.rollback()
		self.db_set("status", "Error")
		self.db_set("error", msg)
		return {
			"status": "Error",
			"message": msg
		}

	def get_supplier_name(self) -> str | None:
		header = self.get_raw_data()
		self.supplier = self.resolve_supplier(
			seller_name=header.get("VENDOR_NAME"),
			tax_id=header.get("VENDOR_VAT_NUMBER") or header.get("TAX_PAYER_ID"),
			iban=header.get("VENDOR_IBAN"),
		)
		return self.supplier

	def get_company(self) -> str | None:
		header = self.get_raw_data()
		self.company = self.resolve_company(
			receiver_name=header.get("RECEIVER_NAME"),
			receiver_address=header.get("RECEIVER_ADDRESS")
		)
		return self.company

	@frappe.whitelist()
	def close_request(self) -> None:
		self.db_set("status", "Closed")

	@frappe.whitelist()
	def open_request(self) -> None:
		self.job = None
		self.error = None
		self.status = "Pending"
		self.db_set("job", None)
		self.db_set("error", None)
		self.set_status(True)

	def get_raw_data(self) -> dict[str, Any]:
		return frappe.parse_json(self.analysis) or {}

	def get_data_from_analysis(self) -> dict[str, Any]:
		return self.get_parsed_data()

	def get_parsed_data(self) -> dict[str, Any]:
		data: dict[str, Any] = {}
		items: list[dict[str, Any]] = []
		parsed_data = self.get_raw_data()
		for key, value in parsed_data.items():
			if key == "_children":
				for child in parsed_data["_children"]:
					row: dict[str, Any] = {}
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

	def find_header_correspondence(self, key: str, value: Any) -> tuple[str | None, Any]:
		pi_fields = [f.fieldname for f in frappe.get_meta("Purchase Invoice").fields]
		locale = frappe.db.get_single_value("System Settings", "language")

		fieldname: str | None = None
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

	def create_supplier_invoice(self) -> Document:
		data: dict = self.get_data_from_analysis()

		doc: SupplierInvoice = frappe.new_doc("Supplier Invoice") # type: ignore
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
		doc.vendor_iban = data.get("vendor_iban")
		doc.match_confidence = getattr(self, "_match_confidence", None) or "low"
		doc.ocr_basket = self.ocr_basket

		return doc.insert(ignore_mandatory=True, ignore_links=True)


def check_pending_analysis() -> None:
	for req in frappe.get_all("OCR Request", filters={"status": ("in", ["Pending", "Error"])}, limit=500):
		try:
			doc = frappe.get_doc("OCR Request", req.name)
			doc.run_method("get_analysis")
			doc.run_method("set_status", commit=True)
		except Exception:
			doc.log_error()
			continue


@frappe.whitelist()
def get_analysis(request_id: str) -> dict[str, Any] | None:
	doc = frappe.get_doc("OCR Request", request_id)
	return doc.get_analysis()


def update_ocr_request_status(doc: Document, method: str) -> None:
	if doc.ocr_request:
		ocr_request = frappe.get_doc("OCR Request", doc.ocr_request)
		ocr_request.set_status(True)
