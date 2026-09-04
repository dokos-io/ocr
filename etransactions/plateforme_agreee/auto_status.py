"""Automatic lifecycle status reporting driven by ERP document workflow.

Mirrors the Odoo auto-event behaviour: ordinary accounting actions
(creating a supplier invoice, submitting a purchase invoice, registering a
payment) trigger the corresponding lifecycle status on the linked e-invoice.

All sends are best-effort and non-blocking: a platform failure is logged but
never prevents the accounting document from being saved/submitted.
"""

import frappe

from etransactions.plateforme_agreee import lifecycle_status
from etransactions.plateforme_agreee.session import get_platform_for_company


def _settings():
	return frappe.get_cached_doc("eTransactions Settings")


def einvoice_for_purchase_invoice(purchase_invoice: str, *, require_flow_id: bool = False) -> str | None:
	"""Resolve the incoming eInvoice behind a Purchase Invoice.

	The Purchase Invoice carries its own ``einvoice`` link (fetched from the Supplier
	Invoice); the two-hop lookup is the fallback for invoices created before that field
	existed.

	``require_flow_id`` is for the *sending* side only: a lifecycle status cannot be
	reported for a flow the platform does not know about. The display side must not use
	it — an e-invoice received by email or file upload has no flow id and still has a
	lifecycle worth showing on the invoice.
	"""
	einvoice = frappe.db.get_value("Purchase Invoice", purchase_invoice, "einvoice")

	if not einvoice:
		supplier_invoice = frappe.db.get_value(
			"Purchase Invoice", purchase_invoice, "supplier_invoice"
		)
		if not supplier_invoice:
			return None
		einvoice = frappe.db.get_value("Supplier Invoice", supplier_invoice, "einvoice")

	if not einvoice:
		return None
	if require_flow_id and not frappe.db.get_value("eInvoice", einvoice, "pa_flow_id"):
		return None
	return einvoice


def _platform_supports(company: str, transaction_type: str, status: str) -> bool:
	"""True if the company's platform can carry this status.

	SuperPDP only supports the statuses that have a native ``fr:`` code; CDAR
	platforms (Esalink/AFNOR) carry every status via the MDT codes.
	"""
	platform = get_platform_for_company(company, transaction_type=transaction_type)
	if not platform:
		return False
	if platform.platform_type == "SuperPDP":
		return bool(lifecycle_status.STATUSES.get(status, {}).get("superpdp"))
	return True


def _send(einvoice_name: str, status: str, transaction_type: str, **kwargs):
	"""Queue an automatic lifecycle status send off the document's transaction.

	The actual platform call runs after commit on the ``short`` queue, so a slow
	or unreachable platform never delays (or rolls back with) the accounting
	document that triggered it.
	"""
	frappe.enqueue(
		"etransactions.plateforme_agreee.auto_status.run_auto_lifecycle_status",
		queue="short",
		enqueue_after_commit=True,
		einvoice_name=einvoice_name,
		status=status,
		transaction_type=transaction_type,
		**kwargs,
	)


def run_auto_lifecycle_status(einvoice_name: str, status: str, transaction_type: str, **kwargs):
	"""Background job: emit a system-initiated lifecycle status to the platform.

	System-initiated, so it bypasses the interactive permission gate on
	``submit_lifecycle_status``. Best-effort: failures are logged, never raised.
	"""
	einvoice = frappe.get_doc("eInvoice", einvoice_name)
	if not get_platform_for_company(einvoice.company, transaction_type=transaction_type):
		# Distinct from a platform that simply can't carry this status (see
		# _platform_supports below): there is nothing to report to yet, which is worth
		# surfacing since it can resolve itself once the platform connection activates.
		einvoice.add_comment(
			"Comment",
			text=frappe._(
				"Lifecycle status '{0}' was not reported: no accredited platform is currently active for {1}."
			).format(lifecycle_status.label(status), transaction_type),
		)
		return
	if not _platform_supports(einvoice.company, transaction_type, status):
		return

	# An ordinary accounting action must never push a status that contradicts what has
	# already been reported — submitting a Purchase Invoice for an invoice the user
	# refused must not report 'Approved'. Skipping is the correct outcome, not an
	# error, so it is recorded as a comment on the eInvoice rather than logged as a
	# failure. Checked after the platform capability so an unsupported status keeps
	# short-circuiting first.
	if error := einvoice.lifecycle_transition_error(status):
		einvoice.add_comment(
			"Comment",
			text=frappe._("Lifecycle status '{0}' was not reported to the accredited platform: {1}").format(
				lifecycle_status.label(status), error
			),
		)
		return

	einvoice.flags.ignore_permissions = True
	try:
		einvoice.submit_lifecycle_status(status, origin="Automatic", **kwargs)
	except Exception:
		frappe.log_error(
			title=f"Auto lifecycle status '{status}' failed",
			reference_doctype="eInvoice",
			reference_name=einvoice_name,
		)


# -----------------------------------------------------------------------------
# Document event handlers (registered in hooks.py)
# -----------------------------------------------------------------------------

def on_supplier_invoice_after_insert(doc, method=None):
	"""Supplier Invoice created from an incoming e-invoice -> 'In Hand'."""
	if not _settings().get("auto_send_in_hand") or not doc.einvoice:
		return
	ei = frappe.db.get_value(
		"eInvoice", doc.einvoice, ["name", "einvoice_type", "pa_flow_id"], as_dict=True
	)
	if ei and ei.einvoice_type == "Incoming" and ei.pa_flow_id:
		_send(ei.name, "in_hand", "purchases")


def _warn_if_lifecycle_closed(einvoice_name: str) -> bool:
	"""Tell the user the invoice's lifecycle is already closed. True when it is.

	Reporting a lifecycle status has no accounting effect, so nothing stops a Purchase
	Invoice from being submitted for an e-invoice that was refused or cancelled on the
	platform. The submission is not blocked — it can be a deliberate correction — but
	the contradiction is made visible instead of silently doing nothing.
	"""
	from etransactions.etransactions.doctype.einvoice_event.einvoice_event import (
		current_lifecycle_state,
	)

	state = current_lifecycle_state(einvoice_name)
	closing = "cancelled" if state["cancelled"] else "refused" if state["refused"] else None
	if not closing:
		return False

	when = frappe.db.get_value(
		"eInvoice Event",
		{"einvoice": einvoice_name, "status": closing},
		"status_datetime",
		order_by="status_datetime desc",
	)
	message = frappe._("The linked e-invoice was reported as '{0}' on the accredited platform").format(
		lifecycle_status.label(closing)
	)
	if when:
		message += f" ({frappe.utils.format_datetime(when)})"
	message += ". " + frappe._("The '{0}' lifecycle status will not be reported.").format(
		lifecycle_status.label("approved")
	)
	frappe.msgprint(message, title=frappe._("Lifecycle already closed"), indicator="orange")
	return True


def on_purchase_invoice_submit(doc, method=None):
	"""Purchase Invoice submitted -> 'Approved'."""
	einvoice = einvoice_for_purchase_invoice(doc.name, require_flow_id=True)
	if not einvoice:
		return

	# Warn whichever way the setting is configured: it is the accounting/platform
	# contradiction that deserves the user's attention, not the skipped send.
	if _warn_if_lifecycle_closed(einvoice):
		return

	if _settings().get("auto_send_approved"):
		_send(einvoice, "approved", "purchases")


def on_payment_entry_submit(doc, method=None):
	"""Payment submitted -> 'Payment Sent' (purchase) / 'Payment Received' (sale).

	Also queues B2C payment data for PPF e-reporting when the paid sale was
	itself e-reported (best-effort, independent of the lifecycle auto-send flag).
	"""
	for ref in doc.get("references", []):
		if ref.reference_doctype == "Sales Invoice":
			try:
				from etransactions.plateforme_agreee.ereporting import capture_sale_payment
				capture_sale_payment(doc, ref.reference_name, ref.allocated_amount, doc.posting_date)
			except Exception:
				frappe.log_error(
					title="e-reporting payment capture failed",
					reference_doctype="Payment Entry",
					reference_name=doc.name,
				)

	if not _settings().get("auto_send_payment"):
		return

	for ref in doc.get("references", []):
		if ref.reference_doctype == "Purchase Invoice":
			einvoice = einvoice_for_purchase_invoice(ref.reference_name, require_flow_id=True)
			if einvoice:
				_send(
					einvoice, "payment_sent", "purchases",
					amount=ref.allocated_amount, currency=doc.paid_from_account_currency,
					payment_date=doc.posting_date,
				)
		elif ref.reference_doctype == "Sales Invoice":
			einvoice = frappe.db.get_value(
				"eInvoice",
				{"sales_invoice": ref.reference_name, "einvoice_type": "Outgoing", "pa_flow_id": ["is", "set"]},
				"name",
			)
			if einvoice:
				_send(
					einvoice, "payment_received", "sales",
					amount=ref.allocated_amount, currency=doc.paid_to_account_currency,
					payment_date=doc.posting_date,
				)
