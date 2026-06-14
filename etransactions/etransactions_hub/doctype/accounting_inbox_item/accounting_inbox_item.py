# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from etransactions.etransactions_hub.utils import copy_file_to_document, get_files_for_document

PROCESSABLE_FILE_TYPES = ["PDF", "XML"]


class AccountingInboxItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		company: DF.Link | None
		created_invoices_basket: DF.Link | None
		created_request: DF.Link | None
		sender: DF.Data | None
		source: DF.Literal["", "Email", "Manual Upload", "Supplier Portal", "API"]
		status: DF.Literal["To Triage", "In Progress", "Processed", "Archived"]
		subject: DF.SmallText | None
		title: DF.Data | None
	# end: auto-generated types

	def before_insert(self):
		if not self.source:
			self.source = "Email" if self.sender else "Manual Upload"

	def validate(self):
		if not self.title:
			self.title = self.subject or _("Inbox item")

	def after_insert(self):
		self._relink_files_after_insert()

	def _relink_files_after_insert(self):
		if self.get("__temporary_name"):
			for file in frappe.get_all(
				"File",
				filters={
					"attached_to_name": self.get("__temporary_name"),
					"attached_to_doctype": self.doctype,
				},
				pluck="name",
			):
				frappe.db.set_value("File", file, "attached_to_name", self.name)

	@frappe.whitelist()
	def create_supplier_invoice(self):
		"""Send the attached files to the supplier invoices processing pipeline.

		Files are copied (not moved) so the inbox item keeps its audit trail.
		"""
		from etransactions.etransactions.doctype.supplier_invoices_basket.supplier_invoices_basket import (
			create_basket_from_files,
		)

		files = get_files_for_document(self.doctype, self.name, file_types=PROCESSABLE_FILE_TYPES)
		if not files:
			frappe.throw(_("No processable file (PDF, XML) is attached to this inbox item"))

		copies = [copy_file_to_document(file["name"], self.doctype, self.name) for file in files]
		basket_name = create_basket_from_files(copies)

		self.db_set("created_invoices_basket", basket_name)
		self.db_set("status", "Processed")

		return basket_name

	@frappe.whitelist()
	def create_request(self, request_type: str | None = None, subject: str | None = None):
		"""Create an Accounting Request prefilled from this inbox item."""
		request = frappe.new_doc("Accounting Request")
		request.subject = subject or self.subject or self.title
		request.request_type = request_type or "Question"
		request.company = self.company
		request.inbox_item = self.name
		request.raised_by = frappe.session.user
		request.insert()

		self.db_set("created_request", request.name)
		if self.status == "To Triage":
			self.db_set("status", "In Progress")

		return request.name

	@frappe.whitelist()
	def archive(self):
		self.db_set("status", "Archived")
