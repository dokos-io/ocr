# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from erpnext import get_default_company

from etransactions.etransactions_hub.utils import copy_file_to_document, get_files_for_document

if TYPE_CHECKING:
	from frappe.core.doctype.communication.communication import Communication

#: reference doctype -> (date field, amount field, party field)
REFERENCE_CONTEXT_FIELDS = {
	"Bank Transaction": ("date", None, "party"),
	"Journal Entry": ("posting_date", "total_debit", "pay_to_recd_from"),
	"Purchase Invoice": ("posting_date", "grand_total", "supplier_name"),
	"Sales Invoice": ("posting_date", "grand_total", "customer_name"),
	"Payment Entry": ("posting_date", "paid_amount", "party_name"),
	"Expense Claim": ("posting_date", "total_claimed_amount", "employee_name"),
	"Supplier Invoice": ("bill_date", "supplier_grand_total", "supplier_name"),
}


class AccountingRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		closing_task: DF.Link | None
		company: DF.Link | None
		context_amount: DF.Currency
		context_date: DF.Date | None
		context_party: DF.Data | None
		description: DF.TextEditor | None
		due_date: DF.Date | None
		inbox_item: DF.Link | None
		justificative_file: DF.Attach | None
		naming_series: DF.Literal["ACC-REQ-.YYYY.-"]
		priority: DF.Literal["Low", "Medium", "High"]
		raised_by: DF.Data | None
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		request_type: DF.Literal["Missing Justificative", "Question", "Correction Needed", "Information"]
		resolved_by: DF.Link | None
		resolved_on: DF.Datetime | None
		status: DF.Literal["Open", "Awaiting Response", "Response Received", "Resolved", "Closed", "Cancelled"]
		subject: DF.Data
	# end: auto-generated types

	def validate(self):
		self._set_defaults()
		self._set_context_from_reference()

	def _set_defaults(self):
		if not self.raised_by and frappe.session.user != "Guest":
			self.raised_by = frappe.session.user

		if not self.company:
			self.company = get_default_company()

	def _set_context_from_reference(self):
		if not (self.reference_doctype and self.reference_name):
			return

		if not frappe.db.exists(self.reference_doctype, self.reference_name):
			frappe.throw(
				_("Reference {0} {1} does not exist").format(
					_(self.reference_doctype), self.reference_name
				)
			)

		date_field, amount_field, party_field = REFERENCE_CONTEXT_FIELDS.get(
			self.reference_doctype, (None, None, None)
		)

		fields = [field for field in (date_field, amount_field, party_field) if field]
		if self.reference_doctype == "Bank Transaction":
			fields.extend(["deposit", "withdrawal"])

		if not fields:
			return

		values = frappe.db.get_value(self.reference_doctype, self.reference_name, fields, as_dict=True)
		if not values:
			return

		self.context_date = values.get(date_field) if date_field else None
		self.context_party = values.get(party_field) if party_field else None

		if self.reference_doctype == "Bank Transaction":
			self.context_amount = flt(values.get("withdrawal")) or flt(values.get("deposit"))
		elif amount_field:
			self.context_amount = flt(values.get(amount_field))

		if frappe.get_meta(self.reference_doctype).has_field("company"):
			reference_company = frappe.db.get_value(self.reference_doctype, self.reference_name, "company")
			if reference_company:
				self.company = reference_company

	def on_communication_update(self, communication: "Communication"):
		"""Called by the framework whenever a Communication linked to this request is saved.

		An inbound reply while the request awaits one means the counterpart answered:
		surface it to the assignees and flip the status.
		"""
		if communication.sent_or_received != "Received":
			return
		if communication.communication_type != "Communication":
			return
		if self.status != "Awaiting Response":
			return

		self.db_set("status", "Response Received")
		self._notify_assignees_of_response(communication)

	def _notify_assignees_of_response(self, communication: "Communication"):
		assignees = [
			user for user in frappe.parse_json(self.get("_assign") or "[]") if user != communication.sender
		]
		if not assignees:
			return

		notification = frappe._dict(
			type="Alert",
			document_type=self.doctype,
			document_name=self.name,
			subject=_("Response received on {0}: {1}").format(self.name, self.subject),
			from_user=frappe.session.user,
		)
		make_notification_logs(notification, assignees)

	@frappe.whitelist()
	def resolve(self):
		if self.status in ("Resolved", "Closed", "Cancelled"):
			frappe.throw(_("This request is already {0}").format(_(self.status)))

		self.status = "Resolved"
		self.resolved_by = frappe.session.user
		self.resolved_on = now_datetime()
		self.save()

	@frappe.whitelist()
	def attach_to_reference(self):
		"""Attach a copy of the collected justificative to the referenced document."""
		if not (self.reference_doctype and self.reference_name):
			frappe.throw(_("This request has no reference document"))

		file_names = self._get_justificative_file_names()
		if not file_names:
			frappe.throw(_("No file to attach. Collect a justificative first."))

		for file_name in file_names:
			copy_file_to_document(file_name, self.reference_doctype, self.reference_name)

		return self.reference_name

	@frappe.whitelist()
	def create_supplier_invoice(self):
		"""Send the collected files to the supplier invoices processing pipeline."""
		from etransactions.etransactions.doctype.supplier_invoices_basket.supplier_invoices_basket import (
			create_basket_from_files,
		)

		file_names = self._get_justificative_file_names()
		if not file_names:
			frappe.throw(_("No file to process. Collect a justificative first."))

		copies = [copy_file_to_document(file_name, self.doctype, self.name) for file_name in file_names]
		return create_basket_from_files(copies)

	def notify_assignees_of_overdue(self):
		assignees = frappe.parse_json(self.get("_assign") or "[]")
		if not assignees:
			return

		notification = frappe._dict(
			type="Alert",
			document_type=self.doctype,
			document_name=self.name,
			subject=_("Overdue accounting request {0}: {1}").format(self.name, self.subject),
		)
		make_notification_logs(notification, assignees)

	def _get_justificative_file_names(self) -> list[str]:
		if self.justificative_file:
			file_name = frappe.db.get_value("File", {"file_url": self.justificative_file}, "name")
			if file_name:
				return [file_name]

		return [file["name"] for file in get_files_for_document(self.doctype, self.name)]


def notify_overdue_requests():
	"""Daily scheduler entry point: remind assignees of overdue open requests."""
	overdue_requests = frappe.get_all(
		"Accounting Request",
		filters={
			"due_date": ("<", frappe.utils.nowdate()),
			"status": ("in", ("Open", "Awaiting Response")),
		},
		pluck="name",
	)

	for request_name in overdue_requests:
		request: AccountingRequest = frappe.get_doc("Accounting Request", request_name)  # type: ignore[assignment]
		request.notify_assignees_of_overdue()
