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


def _einvoice_for_purchase_invoice(purchase_invoice: str) -> str | None:
	"""Resolve the incoming eInvoice behind a Purchase Invoice (via Supplier Invoice)."""
	einvoice = frappe.db.get_value(
		"Supplier Invoice", {"original_invoice": purchase_invoice}, "einvoice"
	)
	if einvoice and frappe.db.get_value("eInvoice", einvoice, "pa_flow_id"):
		return einvoice
	return None


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
	einvoice = frappe.get_doc("eInvoice", einvoice_name)
	if not _platform_supports(einvoice.company, transaction_type, status):
		return
	try:
		einvoice.submit_lifecycle_status(status, **kwargs)
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


def on_purchase_invoice_submit(doc, method=None):
	"""Purchase Invoice submitted -> 'Approved'."""
	if not _settings().get("auto_send_approved"):
		return
	einvoice = _einvoice_for_purchase_invoice(doc.name)
	if einvoice:
		_send(einvoice, "approved", "purchases")


def on_payment_entry_submit(doc, method=None):
	"""Payment submitted -> 'Payment Sent' (purchase) / 'Payment Received' (sale)."""
	if not _settings().get("auto_send_payment"):
		return

	for ref in doc.get("references", []):
		if ref.reference_doctype == "Purchase Invoice":
			einvoice = _einvoice_for_purchase_invoice(ref.reference_name)
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
