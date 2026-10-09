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
from etransactions.etransactions.doctype.ocr_request.mistral_ocr import MistralOCR, OCRRateLimited
from etransactions.utils import parse_number, parse_currency_symbol, date_parser
from etransactions.controllers.entity_resolver import InvoiceEntityResolverMixin, resolve_ocr_buyer_company

if TYPE_CHECKING:
	from etransactions.etransactions.doctype.supplier_invoice.supplier_invoice import SupplierInvoice

# Requests (re)analysed per hourly run of check_pending_analysis, to stay under the OCR service rate limit
PENDING_ANALYSIS_BATCH_SIZE = 50

# Failed analyses retried automatically by check_pending_analysis before the request is left in Error
# for good: a file the OCR service cannot read would otherwise be sent (and billed) every hour.
# Rate limits do not count, they say nothing about the file.
MAX_ANALYSIS_ATTEMPTS = 5

# Prefix of the `error` of a request postponed on a rate limit: the request stays Pending,
# but the answer of the OCR service stays visible on it
RATE_LIMITED = "rate limited"

# https://docs.python.org/3/library/re.html#simulating-scanf
FLOAT_PATTERN = re.compile(r"[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?")

PURCHASE_INVOICE_MAPPING = {
	"INVOICE_RECEIPT_ID": "bill_no",
	"INVOICE_RECEIPT_DATE": "bill_date",
	"VENDOR_NAME": "supplier",
	"RECEIVER_NAME": "company",
	# NB: TAX_PAYER_ID is the *payer* (buyer) tax id, not the seller's — never map it to
	# the supplier tax_id. Only the vendor VAT identifies the supplier.
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
		analysis_attempts: DF.Int
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
		if self.analysis:
			if self.transaction_type == "Purchase Invoice" and not frappe.db.get_value("Supplier Invoice", dict(ocr_request=self.name)):
				self.create_supplier_invoice()
		# The analysis is stored with save(): check_pending_analysis never selects the request again
		self.set_status()

	@frappe.whitelist()
	def make_analysis(self) -> None:
		self.get_analysis()

	def start_ocr_analysis(self) -> None:
		ocr_service = frappe.db.get_single_value("eTransactions Settings", "ocr_service")
		# Mistral OCR is synchronous and receives the file inline: there is no job to start
		if ocr_service != "Mistral OCR":
			self.start_textract_analysis()

	def start_textract_analysis(self) -> None:
		textract = AWSTextractExpense(self)
		jobid = textract.task.start()
		self.job = jobid
		self.db_set("job", jobid)

	def get_analysis(self) -> dict[str, Any] | None:
		if not self.file:
			return self.set_and_return_error("no file", _("No file attached"))

		if not self.job:
			self.start_ocr_analysis()

		try:
			return self.get_ocr_analysis()
		except OCRRateLimited as e:
			return self.postpone_analysis(str(e))
		except Exception as e:
			self.log_error(_("eTransactions Analysis Error"))
			result = self.set_and_return_error(str(e))
			# After the rollback of set_and_return_error, so that the attempt is kept
			self.db_set("analysis_attempts", (self.analysis_attempts or 0) + 1)
			return result

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
				self.error = None
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
				self.set_and_return_error("stale", _("The OCR analysis did not complete within 7 days"))

		elif self.status != "Error":
			self.set_and_return_error("no result", _("The OCR service returned no result"))

		return analysis

	def get_mistral_analysis(self) -> None:
		results = MistralOCR(self).get_ocr_results()

		if not results:
			return

		self.analysis = frappe.as_json(results)
		# Clear the error of a previous failed attempt, or the request would stay in Error
		self.error = None

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
		if self.job or self.analysis:
			status = "Analysis Completed"
		if self.error and not self.analysis and not self.is_rate_limited():
			status = "Error"
		# A processed Supplier Invoice closes the request, whatever the analysis says
		supplier_invoice_status = frappe.db.get_value("Supplier Invoice", dict(ocr_request=self.name), "status")
		if supplier_invoice_status in ("Closed", "Completed"):
			status = supplier_invoice_status

		self.status = status
		if commit:
			self.db_set("status", status)

	def reset_status_and_error(self) -> None:
		self.db_set({"error": "", "analysis_attempts": 0})
		self.set_status(True)

	def is_rate_limited(self) -> bool:
		return (self.error or "").startswith(RATE_LIMITED)

	def postpone_analysis(self, detail: str = "") -> dict[str, str]:
		"""The OCR service is rate limiting: leave the request Pending for the next check_pending_analysis
		run instead of failing it. Nothing was written before the OCR call, so there is nothing to roll back.

		The answer of the service is kept in `error`, and logged the first time only, so that a request
		postponed hour after hour (e.g. an exhausted OCR quota) does not look like it was never sent."""
		if not self.is_rate_limited():
			self.log_error(_("eTransactions Analysis Rate Limited"), detail)

		self.flags.rate_limited = True
		self.db_set({"status": "Pending", "error": f"{RATE_LIMITED}: {detail}"[:1000]})
		return {
			"status": "Pending",
			"message": _("The OCR service is rate limiting requests: the analysis will be retried automatically"),
		}

	def set_and_return_error(self, msg: str, message: str | None = None) -> dict[str, str]:
		"""Store ``msg`` (an error code or raw exception text) and return a displayable message."""
		frappe.db.rollback()
		self.db_set("status", "Error")
		self.db_set("error", msg)
		return {
			"status": "Error",
			"message": message or msg
		}

	def get_supplier_name(self) -> str | None:
		header = self.get_raw_data()
		vendor_tax_id = header.get("VENDOR_VAT_NUMBER")
		# Discard a "vendor" VAT that is in fact the buyer's own VAT — a frequent OCR
		# confusion that otherwise resolves every invoice to whichever supplier happens
		# to share that VAT.
		buyer_vat = header.get("RECEIVER_VAT_NUMBER")
		if (
			vendor_tax_id
			and buyer_vat
			and self._normalize_tax_id(vendor_tax_id) == self._normalize_tax_id(buyer_vat)
		):
			vendor_tax_id = None
		self.supplier = self.resolve_supplier(
			seller_name=header.get("VENDOR_NAME"),
			tax_id=vendor_tax_id,
			iban=header.get("VENDOR_IBAN"),
		)
		return self.supplier

	def get_company(self) -> str | None:
		self.company = resolve_ocr_buyer_company(self.get_raw_data())
		return self.company

	@frappe.whitelist()
	def close_request(self) -> None:
		self.db_set("status", "Closed")

	@frappe.whitelist()
	def open_request(self) -> None:
		self.job = None
		self.error = None
		self.status = "Pending"
		self.analysis_attempts = 0
		self.db_set({"job": None, "error": None, "analysis_attempts": 0})
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

	def resolve_currency(self, supplier: str | None, header: dict[str, Any]) -> str | None:
		"""Resolve the invoice currency: supplier default, then OCR symbol, else None.

		Returning None leaves the Supplier Invoice ``currency`` empty so its
		``fetch_if_empty`` fallback fills the company default currency.
		"""
		if supplier:
			currency = frappe.db.get_value("Supplier", supplier, "default_currency")
			if currency:
				return currency
		for key in ("TOTAL", "AMOUNT_DUE", "SUBTOTAL"):
			currency = parse_currency_symbol(header.get(key))
			if currency:
				return currency
		return None

	def create_supplier_invoice(self) -> Document:
		data: dict = self.get_data_from_analysis()
		header = self.get_raw_data()

		# Never store the buyer's own VAT as the supplier tax_id.
		tax_id = data.get("tax_id")
		buyer_vat = header.get("RECEIVER_VAT_NUMBER")
		if tax_id and buyer_vat and self._normalize_tax_id(tax_id) == self._normalize_tax_id(buyer_vat):
			tax_id = None

		doc: SupplierInvoice = frappe.new_doc("Supplier Invoice") # type: ignore
		# get_parsed_data only resolves the company when the analysis has a RECEIVER_NAME key
		doc.company = data.get("company") or self.get_company()
		doc.supplier = data.get("supplier")
		doc.supplier_name = header.get("VENDOR_NAME")
		doc.bill_no = data.get("bill_no")
		doc.bill_date = data.get("bill_date")
		doc.due_date = data.get("due_date")
		# Post in the supplier's invoice period, not on the day the PDF happened to be
		# imported. `posting_date` defaults to Today, which pushes a late-captured invoice
		# into the wrong month; the extracted invoice date is the accountant's intent.
		if data.get("bill_date"):
			doc.posting_date = data.get("bill_date")
		doc.supplier_net_amount = data.get("net_total")
		doc.supplier_tax_amount = data.get("tax_total")
		doc.supplier_grand_total = data.get("grand_total")
		doc.ocr_request = self.name
		doc.file = self.file
		doc.vendor_address = data.get("vendor_address")
		doc.tax_id = tax_id
		doc.vendor_iban = data.get("vendor_iban")
		currency = self.resolve_currency(doc.supplier, header)
		if currency:
			doc.currency = currency
		doc.match_confidence = getattr(self, "_match_confidence", None) or "low"
		doc.ocr_basket = self.ocr_basket

		return doc.insert(ignore_mandatory=True, ignore_links=True)


def check_pending_analysis() -> None:
	"""Hourly: (re)run the analysis of requests that have none yet, a small batch at a time.

	Requests that failed MAX_ANALYSIS_ATTEMPTS times are left in Error until reset from their form.

	Least recently touched first, so requests failing for good do not starve the others. Stops at
	the first rate limit answer: the next calls would be refused too, and only prolong the limit.
	"""
	requests = frappe.get_all(
		"OCR Request",
		filters={
			"status": ("in", ["Pending", "Error"]),
			"analysis": ("is", "not set"),
			"analysis_attempts": ("<", MAX_ANALYSIS_ATTEMPTS),
		},
		order_by="modified asc",
		pluck="name",
		limit=PENDING_ANALYSIS_BATCH_SIZE,
	)
	for name in requests:
		try:
			doc = frappe.get_doc("OCR Request", name)
			doc.run_method("get_analysis")
			if doc.flags.rate_limited:
				break
			doc.run_method("set_status", commit=True)
		except Exception:
			frappe.log_error(_("eTransactions Analysis Error"), reference_doctype="OCR Request", reference_name=name)
			continue

		# Space out the calls to the OCR service
		time.sleep(1)


@frappe.whitelist()
def get_analysis(request_id: str) -> dict[str, Any] | None:
	doc = frappe.get_doc("OCR Request", request_id)
	return doc.get_analysis()


def update_ocr_request_status(doc: Document, method: str) -> None:
	if doc.ocr_request:
		ocr_request = frappe.get_doc("OCR Request", doc.ocr_request)
		ocr_request.set_status(True)
