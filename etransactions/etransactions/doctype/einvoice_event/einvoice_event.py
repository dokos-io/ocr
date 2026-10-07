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
		company: DF.Link | None
		currency: DF.Link | None
		direction: DF.Literal["out", "in"]
		einvoice: DF.Link | None
		einvoice_type: DF.Literal["", "Incoming", "Outgoing"]
		error_details: DF.SmallText | None
		invoice_reference: DF.Data | None
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
			self.status_label = lifecycle_status.source_label(self.status)

	def after_insert(self):
		# An event can land before its invoice exists (a CDAR flow polled ahead of
		# the invoice it refers to). It is linked later, by adopt_orphan_events or
		# adopt_orphan_events_by_reference, which react to it then.
		if not self.einvoice:
			return
		self.react()

	def react(self):
		"""Act on a counterparty status once the event is linked to its eInvoice."""
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
			# The e-invoicing cancel guard (overrides.sales_invoice.before_cancel)
			# refuses any direct cancellation of a transmitted invoice and points at
			# the guided flow. This *is* the platform-driven flow — the refusal has
			# already been reported by the counterparty — so clear the guard, exactly
			# as cancel_with_lifecycle does. Without this the cancel always throws and
			# the setting is silently inoperative.
			frappe.flags.etransactions_cancel_confirmed = True
			try:
				inv.cancel()
			finally:
				frappe.flags.etransactions_cancel_confirmed = False
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
			escape_html(sales_invoice or self.einvoice),
			escape_html(lifecycle_status.label(self.status) if self.status else ""),
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


def current_lifecycle_state(einvoice: str) -> dict:
	"""The lifecycle state of an eInvoice, derived from the events recorded for it.

	Returns the current status of each axis, the ``refused`` / ``cancelled`` flags and
	the latest status overall::

		{"purchase": "approved", "sale": None, "purchase_at": ..., "sale_at": None,
		 "refused": False, "cancelled": False, "latest": "approved", "latest_at": ...}

	This is the single source of truth for
	:func:`~etransactions.plateforme_agreee.lifecycle_status.transition_error`. It is
	derived on every read rather than denormalised, because polled events carry a
	*platform-supplied* ``status_datetime`` and can be stored out of chronological
	order — only a max-by-datetime read gives the right answer, where an incrementally
	maintained field would be last-write-wins.

	The axis of an event comes from the status, never from ``direction``: the buyer's
	inbound ``refused`` on an invoice we issued is still a purchase-axis status.
	"""
	events = frappe.get_all(
		"eInvoice Event",
		filters={"einvoice": einvoice},
		fields=["status", "status_datetime", "state"],
		# A single poll records a whole batch, so identical status_datetime values are
		# common; creation breaks the tie in insertion order.
		order_by="status_datetime desc, creation desc",
	)

	state = {
		"purchase": None,
		"sale": None,
		"purchase_at": None,
		"sale_at": None,
		"refused": False,
		"cancelled": False,
		"latest": None,
		"latest_at": None,
	}

	for event in events:
		# ``status`` is a free Data field and an errored event never reached the
		# platform, so neither may move the state.
		if event.state == "error" or event.status not in lifecycle_status.STATUSES:
			continue

		if state["latest"] is None:
			state["latest"] = event.status
			state["latest_at"] = event.status_datetime

		# Membership, not recency: a later sale-axis event must not un-refuse an invoice.
		if event.status == "refused":
			state["refused"] = True
		elif event.status == "cancelled":
			state["cancelled"] = True

		side = lifecycle_status.side_of(event.status)
		if side and state[side] is None:
			state[side] = event.status
			state[f"{side}_at"] = event.status_datetime

	return state


def refresh_einvoice_lifecycle_status(einvoice: str | None) -> None:
	"""Refresh the denormalised last-reported-status fields on the eInvoice.

	A projection for the list view and the form, never for validation: the guard
	always reads :func:`current_lifecycle_state` directly. Recomputed from scratch
	instead of being incremented, so an event arriving out of order cannot leave a
	stale value behind. ``update_modified=False`` keeps this bookkeeping from
	provoking "document has been modified" conflicts on the eInvoice.
	"""
	if not einvoice:
		return

	state = current_lifecycle_state(einvoice)
	frappe.db.set_value(
		"eInvoice",
		einvoice,
		{
			"lifecycle_status": state["latest"] or "",
			"lifecycle_status_datetime": state["latest_at"],
		},
		update_modified=False,
	)


def adopt_orphan_events(einvoice: str, pa_flow_id: str) -> int:
	"""Link the events already recorded for a flow to the eInvoice that now exists.

	An event can be polled before the invoice it belongs to — a CDAR lifecycle flow
	arriving ahead of the invoice, or an event recorded from a listing. Rather than
	dropping it (and re-downloading it on every run), it is stored unlinked with its
	``pa_flow_id``, and claimed here. Returns the number adopted.
	"""
	if not pa_flow_id:
		return 0
	return _adopt(einvoice, {"pa_flow_id": pa_flow_id})


def adopt_orphan_events_by_reference(einvoice: str, invoice_reference: str, einvoice_type: str, company: str) -> int:
	"""Link the CDAR events recorded for an invoice number to the eInvoice that now has it.

	A CDAR lifecycle flow is a flow of its own: its ``pa_flow_id`` is never the
	invoice's, so :func:`adopt_orphan_events` cannot claim it. What the CDAR does
	carry is the invoice number, which an incoming eInvoice only learns once its
	file is parsed. Returns the number adopted.
	"""
	if not invoice_reference:
		return 0
	return _adopt(
		einvoice,
		{"invoice_reference": invoice_reference, "einvoice_type": einvoice_type, "company": company},
	)


def _adopt(einvoice: str, filters: dict) -> int:
	orphans = frappe.get_all(
		"eInvoice Event",
		filters={**filters, "einvoice": ["is", "not set"]},
		pluck="name",
	)
	if not orphans:
		return 0

	event = frappe.qb.DocType("eInvoice Event")
	frappe.qb.update(event).set(event.einvoice, einvoice).where(event.name.isin(orphans)).run()
	# This UPDATE bypasses the document layer, so the projection has to be refreshed
	# and the reactions run here too — the adopted events would otherwise never
	# reach the eInvoice, nor raise the ToDo a refusal calls for.
	refresh_einvoice_lifecycle_status(einvoice)
	for name in orphans:
		frappe.get_doc("eInvoice Event", name).react()
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
	invoice_reference: str | None = None,
	einvoice_type: str | None = None,
	company: str | None = None,
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
	is then claimed by :func:`adopt_orphan_events` via ``pa_flow_id``, or by
	:func:`adopt_orphan_events_by_reference` via ``invoice_reference``.

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
		"status_label": lifecycle_status.source_label(status),
		"state": state,
		"status_datetime": status_datetime or frappe.utils.now_datetime(),
		"pa_event_id": pa_event_id,
		"pa_flow_id": pa_flow_id,
		"invoice_reference": invoice_reference,
		"einvoice_type": einvoice_type,
		"company": company,
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
	# Covers both directions: an outbound send and a polled inbound event both move
	# the invoice's lifecycle state.
	refresh_einvoice_lifecycle_status(einvoice)
	return doc
