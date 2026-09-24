import base64
import mimetypes
from typing import TYPE_CHECKING
import frappe

from pydantic import BaseModel, Field
from mistralai.client import Mistral
from mistralai.client.errors import MistralError
from mistralai.client.utils import BackoffStrategy, RetryConfig
from mistralai.extra import response_format_from_pydantic_model


if TYPE_CHECKING:
	from etransactions.etransactions.doctype.ocr_request.ocr_request import OCRRequest


class InvoiceLine(BaseModel):
	ITEM: str | None = Field(description="Line Item/Item Description")
	QUANTITY: str | None = Field(description="Line Item/Quantity")
	PRICE: str | None = Field(description="Line Item/Total Price")
	UNIT_PRICE: str | None = Field(description="Line Item/Unit Price")
	PRODUCT_CODE: str | None = Field(description="Line Item/ProductCode")

class Invoice(BaseModel):
	INVOICE_RECEIPT_DATE: str | None = Field(description="Invoice Receipt Date")
	INVOICE_RECEIPT_ID: str | None = Field(description="Invoice Receipt ID")
	TAX_PAYER_ID: str | None = Field(description="Payer (buyer) Tax/VAT ID — the customer being billed, not the supplier")
	CUSTOMER_NUMBER: str | None = Field(description="Customer Number")
	ACCOUNT_NUMBER: str | None = Field(description="Account Number")
	VENDOR_NAME: str | None = Field(description="Vendor Name")
	RECEIVER_NAME: str | None = Field(description="Receiver/Buyer Name (the customer being billed)")
	VENDOR_ADDRESS: str | None = Field(description="Vendor Address")
	RECEIVER_ADDRESS: str | None = Field(description="Receiver Address")
	ORDER_DATE: str | None = Field(description="Order Date")
	DUE_DATE: str | None = Field(description="Due Date")
	DELIVERY_DATE: str | None = Field(description="Delivery Date")
	PO_NUMBER: str | None = Field(description="PO Number")
	PAYMENT_TERMS: str | None = Field(description="Payment Terms")
	TOTAL: str | None = Field(description="Total")
	AMOUNT_DUE: str | None = Field(description="Amount Due")
	AMOUNT_PAID: str | None = Field(description="Amount Paid")
	SUBTOTAL: str | None = Field(description="Subtotal")
	TAX: str | None = Field(description="Tax")
	SERVICE_CHARGE: str | None = Field(description="Service Charge")
	GRATUITY: str | None = Field(description="Gratuity")
	PRIOR_BALANCE: str | None = Field(description="Prior Balance")
	DISCOUNT: str | None = Field(description="Discount")
	SHIPPING_HANDLING_CHARGE: str | None = Field(description="Shipping and Handling Charge")
	VENDOR_ABN_NUMBER: str | None = Field(description="Vendor ABN Number")
	VENDOR_GST_NUMBER: str | None = Field(description="Vendor GST Number")
	VENDOR_PAN_NUMBER: str | None = Field(description="Vendor PAN Number")
	VENDOR_VAT_NUMBER: str | None = Field(description="Vendor VAT Number")
	RECEIVER_ABN_NUMBER: str | None = Field(description="Receiver ABN Number")
	RECEIVER_GST_NUMBER: str | None = Field(description="Receiver GST Number")
	RECEIVER_PAN_NUMBER: str | None = Field(description="Receiver PAN Number")
	RECEIVER_VAT_NUMBER: str | None = Field(description="Receiver VAT Number")
	VENDOR_PHONE: str | None = Field(description="Vendor Phone")
	RECEIVER_PHONE: str | None = Field(description="Receiver Phone")
	VENDOR_URL: str | None = Field(description="Vendor URL")
	VENDOR_IBAN: str | None = Field(description="Vendor IBAN (bank account number for payment)")
	ADDRESS: str | None = Field(description="Address (Bill To, Ship To, Remit To, Supplier)")
	NAME: str | None = Field(description="Name (Bill To, Ship To, Remit To, Supplier)")
	ADDRESS_BLOCK: str | None = Field(description="Core Address (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	STREET: str | None = Field(description="Street Address (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	CITY: str | None = Field(description="City (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	STATE: str | None = Field(description="State (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	COUNTRY: str | None = Field(description="Country (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	ZIP_CODE: str | None = Field(description="ZIP Code (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	children: list[InvoiceLine] | None = Field(description="Invoice Line Items")



DOCUMENT_ANNOTATION_PROMPT = (
	"This document is a supplier invoice, pro forma invoice or credit note received by the buyer. "
	"Extract the supplier and buyer details, the document header and totals, and every line item. "
	"Keep amounts, dates and identifiers exactly as printed; leave a field empty when it is absent."
)


# Retry 429 and 5xx answers with an exponential backoff (2s, 4s, ... up to 30s, 2 minutes overall).
# The SDK waits for the Retry-After header instead when Mistral sends one.
RETRY_CONFIG = RetryConfig(
	"backoff",
	BackoffStrategy(initial_interval=2_000, max_interval=30_000, exponent=2.0, max_elapsed_time=120_000),
	retry_connection_errors=True,
)


class OCRRateLimited(Exception):
	"""Mistral still answers 429 after the SDK retries: postpone the analysis rather than fail it."""


class MistralOCR:
	def __init__(self, doc: "OCRRequest"):
		ocr_settings = frappe.get_single("eTransactions Settings")
		# The key is not kept on the instance: tracebacks with variables would print it in Error Logs
		self.client = Mistral(
			api_key=ocr_settings.get_password("mistral_api_key"), # type: ignore
			retry_config=RETRY_CONFIG,
		)
		self.doc = doc
		self.file = frappe.get_doc("File", self.doc.file) if self.doc.file else frappe._dict()
		self.model = "mistral-ocr-latest"

	def get_document_url(self) -> str:
		"""Return the file as a base64 data URI, so no upload/signed URL round-trip is needed."""
		if not self.file:
			frappe.throw(frappe._("No encoded file found"))

		content = self.file.get_content() # type: ignore
		if isinstance(content, str):
			content = content.encode()

		mime_type = mimetypes.guess_type(self.file.file_name or "")[0] or "application/pdf" # type: ignore
		return f"data:{mime_type};base64,{base64.b64encode(content).decode()}"

	def get_ocr_results(self):
		try:
			self.ocr_response = self.client.ocr.process(
				model=self.model,
				document={
					"type": "document_url",
					"document_url": self.get_document_url(),
				},
				document_annotation_format=response_format_from_pydantic_model(Invoice),
				document_annotation_prompt=DOCUMENT_ANNOTATION_PROMPT,
			)
		except MistralError as e:
			if e.status_code == 429:
				raise OCRRateLimited(str(e)) from e
			raise

		return self.process_response()

	def process_response(self):
		if not self.ocr_response:
			return {}

		response = frappe.parse_json(self.ocr_response.document_annotation or {})
		children = response.get("children", [])
		response["_children"] = children
		return response

	def delete_file(self, file_id):
		"""Delete a file uploaded by the previous upload + signed URL flow."""
		try:
			self.client.files.delete(file_id=file_id)
		except Exception:
			frappe.log_error("Mistral OCR File Deletion Error")
