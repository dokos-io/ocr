# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import escape_html

from etransactions.plateforme_agreee import lifecycle_status


class eInvoiceEvent(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action_code: DF.Data | None
		action_text: DF.Data | None
		amount: DF.Currency
		comment: DF.SmallText | None
		currency: DF.Link | None
		direction: DF.Literal["out", "in"]
		einvoice: DF.Link
		error_details: DF.SmallText | None
		pa_event_id: DF.Data | None
		pa_flow_id: DF.Data | None
		payment_date: DF.Date | None
		reason_code: DF.Data | None
		reason_text: DF.Data | None
		state: DF.Literal["created", "sent", "done", "error"]
		status: DF.Data | None
		status_datetime: DF.Datetime | None
		status_label: DF.Data | None
	# end: auto-generated types

	def before_insert(self):
		if self.status and not self.status_label:
			self.status_label = lifecycle_status.label(self.status)

	def after_insert(self):
		# Raise a ToDo when the counterparty sends a status that needs attention
		# (dispute / refusal / suspension). Mirrors the Odoo mail-activity behaviour.
		if self.direction == "in" and lifecycle_status.is_warning(self.status):
			self._notify_warning()

	def _notify_warning(self):
		einvoice = frappe.get_doc("eInvoice", self.einvoice)
		owner = None
		if einvoice.sales_invoice:
			owner = frappe.db.get_value("Sales Invoice", einvoice.sales_invoice, "owner")
		owner = owner or einvoice.owner
		if not owner:
			return

		# The comment (and, defensively, the other interpolated values) can carry
		# counterparty-supplied text from an incoming CDAR/event, so escape before
		# building the HTML ToDo description to avoid stored XSS.
		description = frappe._("Invoice {0} received status '{1}' from the accredited platform.").format(
			escape_html(einvoice.sales_invoice or self.einvoice), escape_html(self.status_label or "")
		)
		if self.comment:
			description += f"<br>{escape_html(self.comment)}"

		frappe.get_doc({
			"doctype": "ToDo",
			"allocated_to": owner,
			"reference_type": "eInvoice",
			"reference_name": self.einvoice,
			"priority": "High",
			"description": description,
		}).insert(ignore_permissions=True)


def record_event(
	einvoice: str,
	direction: str,
	status: str,
	*,
	state: str = "sent",
	status_datetime: str | None = None,
	pa_event_id: str | None = None,
	pa_flow_id: str | None = None,
	error_details: str | None = None,
	reason_code: str | None = None,
	reason_text: str | None = None,
	action_code: str | None = None,
	action_text: str | None = None,
	comment: str | None = None,
	amount: float | None = None,
	currency: str | None = None,
	payment_date: str | None = None,
) -> "eInvoiceEvent | None":
	"""Create an eInvoice Event, skipping duplicates.

	Duplicates are detected by ``pa_event_id`` when available, otherwise by the
	``(einvoice, direction, status, status_datetime)`` tuple. Returns the created
	document, or ``None`` when a matching event already exists.
	"""
	if pa_event_id and frappe.db.exists(
		"eInvoice Event", {"einvoice": einvoice, "pa_event_id": pa_event_id}
	):
		return None
	if not pa_event_id and frappe.db.exists(
		"eInvoice Event",
		{
			"einvoice": einvoice,
			"direction": direction,
			"status": status,
			"status_datetime": status_datetime,
		},
	):
		return None

	doc = frappe.get_doc({
		"doctype": "eInvoice Event",
		"einvoice": einvoice,
		"direction": direction,
		"status": status,
		"status_label": lifecycle_status.label(status),
		"state": state,
		"status_datetime": status_datetime or frappe.utils.now_datetime(),
		"pa_event_id": pa_event_id,
		"pa_flow_id": pa_flow_id,
		"error_details": error_details,
		"reason_code": reason_code,
		"reason_text": reason_text,
		"action_code": action_code,
		"action_text": action_text,
		"comment": comment,
		"amount": amount,
		"currency": currency,
		"payment_date": payment_date,
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc
