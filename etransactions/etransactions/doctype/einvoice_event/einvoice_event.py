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
		einvoice: DF.Link | None
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
		# An event can land before its invoice exists (a CDAR flow polled ahead of
		# the invoice it refers to). It is linked by Flow ID later, by
		# adopt_orphan_events; until then there is nothing to react to.
		if not self.einvoice:
			return
		# Raise a ToDo when the counterparty sends a status that needs attention
		# (dispute / refusal / suspension). Mirrors the Odoo mail-activity behaviour.
		if self.direction == "in" and lifecycle_status.is_warning(self.status):
			self._notify_warning()
		# A refusal is definitive: optionally cancel the linked Sales Invoice.
		if self.direction == "in" and self.status == "refused":
			self._maybe_auto_cancel()

	def _maybe_auto_cancel(self):
		"""Cancel the linked Sales Invoice when the customer refuses the e-invoice.

		Gated by the (default-off) ``auto_cancel_on_refusal`` setting because cancel
		is irreversible. Best-effort: a failure is logged, not raised, so it never
		blocks recording the inbound event.
		"""
		if not frappe.db.get_single_value("eTransactions Settings", "auto_cancel_on_refusal"):
			return
		sales_invoice = frappe.db.get_value("eInvoice", self.einvoice, "sales_invoice")
		if not sales_invoice:
			return
		inv = frappe.get_doc("Sales Invoice", sales_invoice)
		if inv.docstatus != 1:
			return
		try:
			inv.flags.ignore_permissions = True
			inv.cancel()
			inv.add_comment(
				"Comment",
				text=frappe._("Cancelled automatically: the customer refused the e-invoice on the accredited platform."),
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Auto-cancel on refusal failed")

	def _notify_warning(self):
		# Two columns are all this needs: loading the whole eInvoice (and its item,
		# tax and payment-term tables) once per event is pure overhead.
		sales_invoice, einvoice_owner = frappe.db.get_value(
			"eInvoice", self.einvoice, ["sales_invoice", "owner"]
		)
		owner = None
		if sales_invoice:
			owner = frappe.db.get_value("Sales Invoice", sales_invoice, "owner")
		owner = owner or einvoice_owner
		if not owner:
			return

		# The comment (and, defensively, the other interpolated values) can carry
		# counterparty-supplied text from an incoming CDAR/event, so escape before
		# building the HTML ToDo description to avoid stored XSS.
		description = frappe._("Invoice {0} received status '{1}' from the accredited platform.").format(
			escape_html(sales_invoice or self.einvoice), escape_html(self.status_label or "")
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


def adopt_orphan_events(einvoice: str, pa_flow_id: str) -> int:
	"""Link the events already recorded for a flow to the eInvoice that now exists.

	An event can be polled before the invoice it belongs to — a CDAR lifecycle flow
	arriving ahead of the invoice, or an event recorded from a listing. Rather than
	dropping it (and re-downloading it on every run), it is stored unlinked with its
	``pa_flow_id``, and claimed here in a single UPDATE. Returns the number adopted.
	"""
	if not pa_flow_id:
		return 0

	orphans = frappe.get_all(
		"eInvoice Event",
		filters={"pa_flow_id": pa_flow_id, "einvoice": ["is", "not set"]},
		pluck="name",
	)
	if not orphans:
		return 0

	event = frappe.qb.DocType("eInvoice Event")
	frappe.qb.update(event).set(event.einvoice, einvoice).where(event.name.isin(orphans)).run()
	return len(orphans)


def record_event(
	einvoice: str | None,
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

	``einvoice`` may be ``None`` for an event polled before its invoice exists; it
	is then claimed by :func:`adopt_orphan_events` via ``pa_flow_id``.

	Duplicates are detected by ``pa_event_id`` when available, otherwise by the
	``(direction, status, status_datetime)`` tuple — scoped to the flow, so an event
	that was recorded unlinked and has since been adopted is still recognised as
	already known. Returns the created document, or ``None`` for a duplicate.
	"""
	scope = {"pa_flow_id": pa_flow_id} if pa_flow_id else {"einvoice": einvoice}
	known = (
		{"pa_event_id": pa_event_id}
		if pa_event_id
		else {"direction": direction, "status": status, "status_datetime": status_datetime}
	)
	if frappe.db.exists("eInvoice Event", {**scope, **known}):
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
