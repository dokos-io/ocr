# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

"""Where a received e-invoice stands on the accredited platform, in plain words.

The lifecycle panel used to hand the user raw material — a transmission ribbon built
for outgoing flows, one chip per axis and an events table — and leave the reading to
them. This module does the reading once, on the server, for an invoice we *received*:

- one headline (tone, short pill, sentence, explanation), picked by :data:`PRECEDENCE`
  order so that what needs attention first is what is shown;
- four steps — received, in hand, decision, payment — the buyer's path through the
  French lifecycle;
- the history, newest first, saying who did what and whether it reached the platform.

It only reads: statuses, transitions and wording all come from
:mod:`~etransactions.plateforme_agreee.lifecycle_status` and the recorded events.
"""

import frappe
from frappe import _
from frappe.utils import fmt_money, get_fullname

from etransactions.plateforme_agreee import lifecycle_status

# Decision statuses on the purchase axis: what the buyer concluded about the invoice.
DECISIONS = ("approved", "partially_approved", "dispute", "suspended", "refused")

# Registry decoration -> Desk indicator colour.
TONES = {"success": "green", "danger": "red", "warning": "orange", "info": "blue"}

# The headline for each current purchase-axis status, in precedence order after the
# delivery and file problems (see :func:`_headline`).
PRECEDENCE = (
	"cancelled",
	"refused",
	"payment_sent",
	"approved",
	"partially_approved",
	"dispute",
	"suspended",
	"in_hand",
)

# Automatic sends are inserted by the scheduler or a document hook, never by a person.
SYSTEM_USERS = ("Administrator", "Guest")


def get_overview(einvoice: str) -> dict | None:
	"""The overview of an incoming eInvoice, or ``None`` for an outgoing one.

	Permission checks are the caller's job: this is reached through the whitelisted
	wrapper in ``einvoice.py``, which checks read access first.
	"""
	from etransactions.etransactions.doctype.einvoice.einvoice import get_supported_lifecycle_statuses
	from etransactions.etransactions.doctype.einvoice_event.einvoice_event import current_lifecycle_state

	doc = frappe.db.get_value(
		"eInvoice",
		einvoice,
		[
			"name",
			"einvoice_type",
			"company",
			"creation",
			"pa_flow_id",
			"pa_platform_name",
			"pa_submitted_at",
			"pa_content_state",
			"pa_content_error",
			"pa_content_attempts",
			"pa_content_last_attempt",
		],
		as_dict=True,
	)
	if not doc or doc.einvoice_type != "Incoming":
		return None

	events = frappe.get_all(
		"eInvoice Event",
		filters={"einvoice": einvoice},
		fields=[
			"name",
			"owner",
			"direction",
			"status",
			"status_label",
			"state",
			"status_datetime",
			"reason_code",
			"reason_text",
			"comment",
			"error_details",
			"amount",
			"currency",
		],
		order_by="status_datetime asc, creation asc",
	)
	state = current_lifecycle_state(einvoice)
	supported = get_supported_lifecycle_statuses(einvoice)
	reportable = {s["status"] for s in supported["statuses"]}
	failed = _undelivered_event(events)
	platform = doc.pa_platform_name or _("the accredited platform")

	return {
		"einvoice": doc.name,
		"platform": doc.pa_platform_name,
		"flow_id": doc.pa_flow_id,
		**_headline(doc, state, failed, platform),
		"steps": _steps(doc, state, events, failed),
		"history": _history(doc, events, failed, reportable, platform),
		"actions": supported["statuses"],
		"blocked_reason": supported["blocked_reason"],
		"can_retry_download": bool(doc.pa_flow_id and doc.pa_content_state in ("pending", "error")),
	}


def _undelivered_event(events: list) -> dict | None:
	"""The latest outgoing status the platform did not accept, unless it was re-sent since.

	An errored send never moves the lifecycle state, so it would otherwise vanish from
	view while the user believes the supplier was told.
	"""
	for event in reversed(events):
		if event.direction != "out":
			continue
		if event.state == "error":
			return event
		# The most recent outgoing send went through: an older failure was superseded.
		return None
	return None


def _headline(doc, state: dict, failed, platform: str) -> dict:
	if failed:
		return {
			"key": "not_delivered",
			"tone": "red",
			"pill": _("Not delivered"),
			"headline": _("'{0}' did not reach the supplier").format(_status_label(failed.status)),
			"summary": _(
				"{0} did not accept this status, so nothing was communicated to the supplier. Fix the cause, then retry."
			).format(platform),
		}

	if doc.pa_flow_id and doc.pa_content_state in ("pending", "error"):
		if doc.pa_content_state == "error":
			summary = _("The original file could not be downloaded or read from {0}.").format(platform)
		else:
			summary = _("{0} announced this invoice but its file has not been downloaded yet.").format(
				platform
			)
		return {
			"key": "file_pending",
			"tone": "orange",
			"pill": _("File not downloaded"),
			"headline": _("Waiting for the original file"),
			"summary": summary,
		}

	current = "cancelled" if state["cancelled"] else "refused" if state["refused"] else state["purchase"]
	if current in PRECEDENCE:
		return {"key": current, **HEADLINES[current]()}

	if not doc.pa_flow_id:
		return {
			"key": "off_platform",
			"tone": "gray",
			"pill": _("Not on a platform"),
			"headline": _("Received outside an accredited platform"),
			"summary": _(
				"This e-invoice did not come through an accredited platform, so no status can be reported."
			),
		}

	return {
		"key": "received",
		"tone": "gray",
		"pill": _("Received"),
		"headline": _("Received — not yet acknowledged"),
		"summary": _("The supplier has not been told that you have this invoice yet."),
	}


# Callables so the wording is translated per request, in the reader's language.
HEADLINES = {
	"cancelled": lambda: {
		"tone": "red",
		"pill": _("Cancelled"),
		"headline": _("Cancelled on the platform"),
		"summary": _(
			"This invoice was cancelled and no longer needs to be paid. No further status can be reported."
		),
	},
	"refused": lambda: {
		"tone": "red",
		"pill": _("Refused"),
		"headline": _("Refused — this invoice will not be paid"),
		"summary": _("Refusal is final. The supplier must issue a new invoice if an amount is still due."),
	},
	"payment_sent": lambda: {
		"tone": "green",
		"pill": _("Paid"),
		"headline": _("Paid — payment reported to the supplier"),
		"summary": _("Nothing is left to do on the platform, unless a new dispute arises."),
	},
	"approved": lambda: {
		"tone": "green",
		"pill": _("Approved"),
		"headline": _("Approved — awaiting payment"),
		"summary": _(
			"The supplier knows the invoice is accepted. Report the payment once the transfer has left."
		),
	},
	"partially_approved": lambda: {
		"tone": "orange",
		"pill": _("Partially approved"),
		"headline": _("Partially approved — waiting for the supplier"),
		"summary": _(
			"Only part of the invoice was accepted. The supplier should send a credit note or a corrected invoice."
		),
	},
	"dispute": lambda: {
		"tone": "orange",
		"pill": _("Disputed"),
		"headline": _("Disputed — waiting for the supplier"),
		"summary": _(
			"The supplier should send a corrected invoice or a credit note. You can still approve or refuse this one."
		),
	},
	"suspended": lambda: {
		"tone": "orange",
		"pill": _("Suspended"),
		"headline": _("Suspended — supporting documents missing"),
		"summary": _("Payment is on hold until the supplier provides what is missing."),
	},
	"in_hand": lambda: {
		"tone": "blue",
		"pill": _("Awaiting decision"),
		"headline": _("Awaiting your decision"),
		"summary": _(
			"The supplier knows you have the invoice. Once it is checked, approve it, or dispute or refuse it."
		),
	},
}


def _steps(doc, state: dict, events: list, failed) -> list[dict]:
	delivered = [e for e in events if e.state != "error" and e.status in lifecycle_status.STATUSES]

	def last(statuses):
		return next((e for e in reversed(delivered) if e.status in statuses), None)

	received = {
		"key": "received",
		"label": _("Received"),
		"state": "done",
		"at": doc.pa_submitted_at or doc.creation,
	}
	if doc.pa_content_state == "pending" and doc.pa_flow_id:
		received.update(state="warning", note=_("File not downloaded"))
	elif doc.pa_content_state == "error" and doc.pa_flow_id:
		received.update(state="error", note=_("File could not be read"))

	in_hand_event = last(("in_hand",))
	decision_event = last(DECISIONS)
	payment_event = last(("payment_sent",))
	closed = state["refused"] or state["cancelled"]

	in_hand = {"key": "in_hand", "label": lifecycle_status.label("in_hand"), "state": "todo"}
	if in_hand_event:
		in_hand.update(state="done", at=in_hand_event.status_datetime)
	elif decision_event or payment_event:
		# Nothing forces 'in hand' to be reported before a decision.
		in_hand.update(state="done", note=_("Not reported"))
	elif received["state"] == "done" and doc.pa_flow_id and not closed:
		in_hand.update(state="current", note=_("Not reported yet"))

	decision = {"key": "decision", "label": _("Decision"), "state": "todo"}
	if decision_event:
		decision.update(
			label=lifecycle_status.label(decision_event.status),
			state={"approved": "done", "refused": "error"}.get(decision_event.status, "warning"),
			at=decision_event.status_datetime,
			note=lifecycle_status.reason_label(decision_event.reason_code)
			if decision_event.reason_code
			else None,
		)
	elif payment_event:
		decision.update(state="done", note=_("Not reported"))
	elif in_hand["state"] == "done" and not closed:
		decision.update(state="current", note=_("Your move"))

	payment = {"key": "payment", "label": _("Payment"), "state": "todo"}
	if payment_event:
		payment.update(label=_("Paid"), state="done", at=payment_event.status_datetime)
	elif closed:
		payment.update(state="skipped", note=_("Not applicable"))
	elif decision_event and decision_event.status == "approved":
		payment.update(state="current", note=_("Not paid yet"))

	steps = [received, in_hand, decision, payment]

	if state["cancelled"]:
		for step in steps:
			if step["state"] in ("todo", "current"):
				step.update(state="skipped", note=_("Not applicable"))

	if failed:
		index = 1 if failed.status == "in_hand" else 3 if failed.status == "payment_sent" else 2
		steps[index].update(
			label=_status_label(failed.status),
			state="error",
			at=failed.status_datetime,
			note=_("Not delivered"),
		)

	return steps


def _history(doc, events: list, failed, reportable: set, platform: str) -> list[dict]:
	rows = []

	if doc.pa_flow_id:
		rows.append(
			{
				"title": _("Invoice received"),
				"actor": platform,
				"actor_tone": "purple",
				"tone": "purple",
				"at": doc.pa_submitted_at or doc.creation,
			}
		)
	else:
		rows.append(
			{
				"title": _("e-Invoice imported"),
				"actor": "Dokos",
				"actor_tone": "gray",
				"tone": "gray",
				"at": doc.creation,
			}
		)

	for event in events:
		known = event.status in lifecycle_status.STATUSES
		decoration = (lifecycle_status.STATUSES.get(event.status) or {}).get("decoration")
		row = {
			"title": _status_label(event.status) if known else _(event.status_label or event.status or ""),
			"code": lifecycle_status.STATUSES[event.status]["mdt105"] if known else None,
			"at": event.status_datetime,
			"tone": "red" if event.state == "error" else TONES.get(decoration, "gray"),
			"reason": lifecycle_status.reason_label(event.reason_code) if event.reason_code else None,
			"comment": event.comment,
			"detail": fmt_money(event.amount, currency=event.currency) if event.amount else None,
		}
		if event.direction == "out":
			automatic = event.owner in SYSTEM_USERS
			row.update(
				actor=_("Sent automatically")
				if automatic
				else _("Sent by {0}").format(get_fullname(event.owner)),
				actor_tone="blue",
				delivery=event.state,
				delivery_label=_delivery_label(event.state, platform),
				error=event.error_details if event.state == "error" else None,
			)
			if failed and event.name == failed.name and event.status in reportable:
				row["retry_status"] = event.status
		else:
			row.update(actor=_("From the supplier"), actor_tone="purple")
		rows.append(row)

	# The file download happens after the flow is recorded; a problem with it is the
	# latest thing that happened to the invoice.
	if doc.pa_flow_id and doc.pa_content_state in ("pending", "error"):
		attempts = doc.pa_content_attempts or 0
		rows.append(
			{
				"title": _("File download failed")
				if doc.pa_content_state == "error"
				else _("File not downloaded yet"),
				"actor": "Dokos",
				"actor_tone": "gray",
				"tone": "red" if doc.pa_content_state == "error" else "orange",
				"at": doc.pa_content_last_attempt,
				"detail": _content_attempts_detail(attempts),
				"error": doc.pa_content_error if doc.pa_content_state == "error" else None,
			}
		)

	rows.reverse()
	return rows


def _content_attempts_detail(attempts: int) -> str | None:
	from etransactions.plateforme_agreee.flow import MAX_CONTENT_ATTEMPTS

	if attempts >= MAX_CONTENT_ATTEMPTS:
		return _("Tried {0} times. Automatic retries have stopped.").format(attempts)
	return _("Tried {0} times").format(attempts) if attempts > 1 else None


def _delivery_label(state: str, platform: str) -> str:
	if state == "done":
		return _("Accepted by {0}").format(platform)
	if state == "sent":
		return _("Sent to {0}, awaiting acknowledgement").format(platform)
	if state == "created":
		return _("Queued for sending")
	return _("Not delivered — rejected by {0}").format(platform)


def _status_label(status: str | None) -> str:
	return lifecycle_status.label(status) if status else ""


def retry_content_fetch(einvoice: str) -> None:
	"""Queue a new download of the original file, instead of waiting for the next sweep."""
	from etransactions.plateforme_agreee.flow import _enqueue_content_fetch

	doc = frappe.db.get_value("eInvoice", einvoice, ["pa_flow_id", "pa_content_state"], as_dict=True)
	if not doc or not doc.pa_flow_id or doc.pa_content_state not in ("pending", "error"):
		frappe.throw(_("There is no pending download for this eInvoice."))
	_enqueue_content_fetch(einvoice)
