from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

def on_submit(doc, method):
	"""Best-effort: queue an international B2B (B2Bi) purchase for PPF e-reporting.

	Never blocks the submission — failures are logged, not raised.
	"""
	try:
		from etransactions.plateforme_agreee.ereporting import capture_purchase_transaction

		capture_purchase_transaction(doc)
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("e-reporting purchase capture failed"))


def after_mapping(doc, method, source):
	"""Carry the Supplier Invoice context onto an invoice mapped from an order or receipt.

	`source` is whichever document the user mapped from; today only Purchase Order carries
	`supplier_invoice`, so anything else no-ops here.

	The invoice must inherit the Supplier Invoice's posting date. Without `set_posting_time`,
	`validate_posting_time` silently rewrites `posting_date` to *now*, so an invoice captured
	for June but mapped in July lands in the wrong period. `SupplierInvoice.get_purchase_invoice`
	already does this for the invoice-first route; this covers the order-first one.
	"""
	if not source.get("supplier_invoice"):
		return

	doc.supplier_invoice = source.supplier_invoice
	doc.ocr_original_file = source.get("ocr_original_file")

	posting_date = frappe.db.get_value("Supplier Invoice", source.supplier_invoice, "posting_date")
	if posting_date:
		doc.posting_date = posting_date
		doc.set_posting_time = 1

def validate_over_billing(doc, method):
	if not doc.supplier_invoice:
		return

	if doc.flags.ignore_mandatory_pr:
		return

	settings = frappe.get_single("eTransactions Settings")
	if doc.is_return or not settings.reconcile_with_purchase_receipts: # type: ignore
		return

	total_per_ref = defaultdict(dict)
	for item in doc.items:
		if item.purchase_receipt:
			pr = frappe.get_doc("Purchase Receipt", item.purchase_receipt)
			total_per_ref[item.purchase_receipt] = pr.net_total - (flt(pr.per_billed) / 100.0 * pr.net_total)
		elif not doc.flags.ignore_mandatory_pr:
			frappe.throw(_("All purchase invoice rows must be linked with a purchase receipt"))

	pending_invoicing_amount = sum(total_per_ref.values())

	max_amount = min(
		flt(pending_invoicing_amount) + flt(settings.max_difference_amount),
		flt(pending_invoicing_amount) * (1 + flt(settings.max_difference_percentage_on_net_total) / 100)
	)

	precision = frappe.db.get_default("currency_precision")
	if flt(doc.net_total, precision=precision) > flt(max_amount, precision=precision): # type: ignore
		message = _("This purchase invoice can not be submitted because the net total is higher than {0}").format(fmt_money(max_amount, currency=doc.currency))

		if method == "validate":
			frappe.msgprint(message, alert=True, indicator="red")

		elif method =="before_submit":
			frappe.throw(message)