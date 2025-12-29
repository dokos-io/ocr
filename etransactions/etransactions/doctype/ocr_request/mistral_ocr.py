from typing import TYPE_CHECKING
import frappe

from pydantic import BaseModel, Field
from mistralai import Mistral
from mistralai.extra import response_format_from_pydantic_model
from mistralai.models.sdkerror import SDKError


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
	TAX_PAYER_ID: str | None = Field(description="Invoice Tax Payer ID")
	CUSTOMER_NUMBER: str | None = Field(description="Customer Number")
	ACCOUNT_NUMBER: str | None = Field(description="Account Number")
	VENDOR_NAME: str | None = Field(description="Vendor Name")
	RECEIVER_NAME: str | None = Field(description="Vendor Address")
	VENDOR_ADDRESS: str | None = Field(description="Vendor Name")
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
	ADDRESS: str | None = Field(description="Address (Bill To, Ship To, Remit To, Supplier)")
	NAME: str | None = Field(description="Name (Bill To, Ship To, Remit To, Supplier)")
	ADDRESS_BLOCK: str | None = Field(description="Core Address (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	STREET: str | None = Field(description="Street Address (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	CITY: str | None = Field(description="City (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	STATE: str | None = Field(description="State (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	COUNTRY: str | None = Field(description="Country (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	ZIP_CODE: str | None = Field(description="ZIP Code (Vendor, Receiver, Bill To, Ship To, Remit To, Supplier)")
	children: list[InvoiceLine] | None = Field(description="Invoice Line Items")



class MistralOCR:
	def __init__(self, doc: "OCRRequest"):
		ocr_settings = frappe.get_single("eTransactions Settings")
		self.api_key = ocr_settings.get_password("mistral_api_key")
		self.client = Mistral(api_key=self.api_key) # type: ignore
		self.doc = doc
		self.file = frappe.get_doc("File", self.doc.file) if self.doc.file else frappe._dict()
		self.uploaded_file = None
		self.signed_url = None
		self.model = "mistral-etransactions-latest"


	def upload_file(self):
		if not self.file:
			frappe.throw(frappe._("No encoded file found"))

		self.uploaded_file = self.client.files.upload(
			file={
				"file_name": self.file.file_name, # type: ignore
				"content": self.file.get_content(), # type: ignore
			},
			purpose="etransactions"
		)

		return self.uploaded_file.id

	def get_signed_url(self, file_id):
		try:
			self.signed_url = self.client.files.get_signed_url(file_id=file_id)
			return self.signed_url
		except SDKError as e:
			if e.status_code == 404:
				file_id = self.upload_file()
				self.doc.job = file_id
				self.doc.db_set("job", file_id)
				self.signed_url = self.client.files.get_signed_url(file_id=file_id)
				return self.signed_url



	def get_ocr_results(self, url):
		try:
			self.ocr_response = self.client.etransactions.process(
				model=self.model,
				document={
					"type": "document_url",
					"document_url": url,
				},
				include_image_base64=True,
				document_annotation_format=response_format_from_pydantic_model(Invoice)
			)

			return self.process_response()
		except Exception:
			frappe.log_error("Mistral eTransactions Error")

	def process_response(self):
		if not self.ocr_response:
			return {}

		response = frappe.parse_json(self.ocr_response.document_annotation or {})
		children = response.get("children", [])
		response["_children"] = children
		return response

	def delete_file(self, file_id):
		try:
			self.client.files.delete(file_id=file_id)
		except Exception:
			frappe.log_error("Mistral eTransactions File Deletion Error")




