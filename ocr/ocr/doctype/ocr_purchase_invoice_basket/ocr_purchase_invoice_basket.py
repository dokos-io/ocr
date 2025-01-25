# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappe.email.inbox import link_communication_to_document


AUTHORIZED_FILE_TYPES = ["PDF"]

class OCRPurchaseInvoiceBasket(Document):
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
			self.create_requests()

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
	def create_requests(self):
		if linked_files := self.get_all_files():
			for file in linked_files:
				request = frappe.new_doc("OCR Request")
				request.ocr_basket = self.name
				request.filename = file.get("file_name")
				request.file = file.get("name")
				request.insert()

			self.db_set("status", "In Progress")
		else:
			self.db_set("error", _("No PDF file found in this basket"))
			self.db_set("status", "Closed")

	def relink_files_after_insert(self):
		if self.get("__temporary_name"):
			for file in frappe.get_all("File", filters=dict(
				attached_to_name=self.get("__temporary_name"),
				attached_to_doctype=self.doctype,
			), pluck="name"):
				frappe.db.set_value("File", file, "attached_to_name", self.name)


	def set_status(self):
		associated_requests = frappe.get_all("OCR Request", filters={"ocr_basket": self.name}, fields=["name", "status"])
		if not associated_requests:
			try:
				if self.status != "Not Started":
					self.db_set("status", "Not Started")
				self.run_method("create_requests")
			except Exception:
				self.log_error()

		elif all([a.status in ["Closed", "Completed", "Analysis Completed"] for a in associated_requests]):
			frappe.db.set_value("OCR Purchase Invoice Basket", self.name, "status", "Completed")



@frappe.whitelist()
def make_basket_from_communication(communication, basket_type, ignore_communication_links=False):
	communication_doc = frappe.get_doc("Communication", communication)

	basket = frappe.new_doc("OCR Purchase Invoice Basket")
	basket.document_type = basket_type
	basket.subject = frappe.as_unicode(communication_doc.subject)[:140]
	basket.sender = frappe.as_unicode(communication_doc.sender)

	basket.flags.ignore_mandatory = True
	basket.insert(ignore_permissions=True, ignore_if_duplicate=True)

	link_communication_to_document(communication_doc, "OCR Purchase Invoice Basket", basket.name, ignore_communication_links)

	basket.run_method("create_requests")

	return basket


@frappe.whitelist()
def check_ocr_basket_status():
	for ocr_basket in frappe.get_all("OCR Purchase Invoice Basket", filters={"status": "In Progress"}):
		frappe.get_doc("OCR Purchase Invoice Basket", ocr_basket.name).run_method("set_status")