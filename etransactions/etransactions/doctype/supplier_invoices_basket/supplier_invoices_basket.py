# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.model.document import Document

from frappe.email.inbox import link_communication_to_document

from etransactions.etransactions.doctype.einvoice.parser import eInvoiceParser
from etransactions.etransactions.doctype.etransactions_settings.etransactions_settings import eTransactionsSettings

if TYPE_CHECKING:
	from frappe.core.doctype.file.file import File
	from etransactions.etransactions.doctype.ocr_request.ocr_request import OCRRequest
	from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice

AUTHORIZED_FILE_TYPES = ["PDF"]


class SupplierInvoicesBasket(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		error: DF.SmallText | None
		sender: DF.Data | None
		status: DF.Literal["Not Started", "In Progress", "Completed", "Closed"]
		subject: DF.SmallText | None
		title: DF.Data | None
	# end: auto-generated types

	def validate(self):
		if not self.title and self.name:
			self.title = _("Basket n°") + self.name

	def after_insert(self):
		self.relink_files_after_insert()

		if self.flags and self.flags._from_incoming_email:
			frappe.enqueue_doc(
				self.doctype,
				self.name,
				"route_invoices",
				queue="default",
				enqueue_after_commit=True,
			)

	def get_linked_communications(self):
		return frappe.get_all("Communication", filters={
			"reference_doctype": self.doctype,
			"reference_name": self.name
		}, pluck="name")

	def get_files_from_communication(self, communication_name):
		return frappe.get_all("File", filters={
			"attached_to_doctype": "Communication",
			"attached_to_name": communication_name,
			"file_type": ("in", AUTHORIZED_FILE_TYPES)
		}, fields=["file_name", "name"])

	def get_files(self):
		return frappe.get_all("File", filters={
			"attached_to_doctype": self.doctype,
			"attached_to_name": self.name
		}, fields=["file_name", "name"])

	def get_all_files(self):
		files = self.get_files()
		for communication in self.get_linked_communications():
			files.extend(
				self.get_files_from_communication(communication)
			)
		return files

	@frappe.whitelist()
	def route_invoices(self):
		"""
		Always check first if invoice is an einvoice.
		Else send it to OCR.
		"""
		self.db_set("status", "In Progress")
		if linked_files := self.get_all_files():
			for file in linked_files:
				try:
					file_doc: File = frappe.get_doc("File", file["name"]) # type: ignore

					# Parse the XML before creating the eInvoice to throw if not an eInvoice
					_xml_bytes, xml_format = eInvoiceParser.get_xml_bytes(file_doc)

					einvoice: eInvoice = frappe.new_doc("eInvoice") # type: ignore
					einvoice.supplier_invoices_basket = self.name
					einvoice.einvoice = file["name"]
					einvoice.insert()
				except Exception:
					#TODO: Handle errors for UX
					frappe.clear_messages()

					if not is_ocr_service_configured():
						frappe.msgprint("File {} is not an eInvoice and needs to be processed with an OCR Service.<br>Activate Amazon Textract or Mistral in eTransactions Settings.".format(file["name"]), alert=True)
						continue

					request: OCRRequest = frappe.new_doc("OCR Request") # type: ignore
					request.ocr_basket = self.name
					request.filename = file.get("file_name")
					request.file = file.get("name")
					request.insert()

			self.db_set("status", "Completed")
		else:
			self.db_set("error", _("No matching supplier format file (PDF, XML) found in this basket"))
			self.db_set("status", "Closed")

	def relink_files_after_insert(self):
		if self.get("__temporary_name"):
			for file in frappe.get_all("File", filters=dict(
				attached_to_name=self.get("__temporary_name"),
				attached_to_doctype=self.doctype,
			), pluck="name"):
				frappe.db.set_value("File", file, "attached_to_name", self.name)


def is_ocr_service_configured() -> bool:
	settings: eTransactionsSettings = frappe.get_cached_doc("eTransactions Settings")  # type: ignore[assignment]
	if not settings.ocr_service:
		return False
	if settings.ocr_service == "Amazon Textract":
		return bool(settings.aws_textract_key and settings.aws_textract_secret)
	if settings.ocr_service == "Mistral OCR":
		return bool(settings.mistral_api_key)
	return False


@frappe.whitelist()
def create_basket_from_files(file_names: list[str] | str):
	if isinstance(file_names, str):
		file_names = frappe.parse_json(file_names)

	basket = frappe.new_doc("Supplier Invoices Basket")
	basket.insert()

	for file_name in file_names:
		frappe.db.set_value("File", file_name, {
			"attached_to_doctype": "Supplier Invoices Basket",
			"attached_to_name": basket.name
		})

	basket.route_invoices()

	return basket.name


@frappe.whitelist()
def make_basket_from_communication(communication: str, basket_type: str, ignore_communication_links: bool | None = False):
	communication_doc = frappe.get_doc("Communication", communication)

	basket = frappe.new_doc("Supplier Invoices Basket")
	basket.document_type = basket_type
	basket.subject = frappe.as_unicode(communication_doc.subject)[:140]
	basket.sender = frappe.as_unicode(communication_doc.sender)

	basket.flags.ignore_mandatory = True
	basket.insert(ignore_permissions=True, ignore_if_duplicate=True)

	link_communication_to_document(communication_doc, "Supplier Invoices Basket", basket.name, ignore_communication_links)

	basket.run_method("create_requests")

	return basket

