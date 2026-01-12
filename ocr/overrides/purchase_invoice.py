from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

def after_mapping(doc, method, purchase_order):
	if purchase_order.get("pending_purchase_invoice"):
		doc.pending_purchase_invoice = purchase_order.pending_purchase_invoice
		doc.ocr_original_file = purchase_order.get("ocr_original_file")

def validate_over_billing(doc, method):
	if not doc.pending_purchase_invoice:
		return

	if doc.flags.ignore_mandatory_pr:
		return

	settings = frappe.get_single("OCR Settings")
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