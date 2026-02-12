from typing import TYPE_CHECKING
import frappe

from frappe import _
from frappe.utils.data import date_diff

from etransactions.utils import EInvoiceProfile


if TYPE_CHECKING:
	from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice


def on_validate(doc, method):
	if not doc.etransaction_profile:
		return

	for tax_row in doc.taxes:
		if tax_row.charge_type == "On Item Quantity":
			frappe.msgprint(
				_("{0} row #{1}: Type '{2}' is not supported in e-invoice").format(
					_(doc.meta.get_label("taxes")), tax_row.idx, _(tax_row.charge_type)
				),
				alert=True,
				indicator="orange",
			)

		if (
			tax_row.charge_type == "Actual"
			and EInvoiceProfile(doc.einvoice_profile) < EInvoiceProfile.EXTENDED
		):
			frappe.msgprint(
				_(
					"{0} row #{1}: The charge type 'Actual' is only supported in the eInvoice profiles 'EXTENDED' and 'FACTUR-X'."
				).format(_(doc.meta.get_label("taxes")), tax_row.idx),
				alert=True,
				indicator="orange",
			)

	modes_of_payment = set()
	for ps in doc.payment_schedule:
		if ps.discount_date and date_diff(ps.discount_date, doc.posting_date) < 0:
			frappe.msgprint(
				_("{0} row #{1}: Discount Date should be after Posting Date").format(
					_(doc.meta.get_label("payment_schedule")), ps.idx
				),
				alert=True,
				indicator="orange",
			)

		if ps.mode_of_payment:
			modes_of_payment.add(ps.mode_of_payment)

	if len(modes_of_payment) > 1:
		frappe.msgprint(
			_("{0}: Only one mode of payment will be considered in the e-invoice.").format(
				_(doc.meta.get_label("payment_schedule"))
			),
			alert=True,
			indicator="orange",
		)

	if doc.discount_amount:
		frappe.msgprint(
			_("A document level discount is currently not supported in the e-invoice."),
			alert=True,
			indicator="orange",
		)


def on_update(doc, method):
	"""Create EDocument when Sales Invoice is saved (if profile setting enabled)."""
	if not doc.name or not doc.etransaction_profile:
		return

	if doc.docstatus == 1:
		return

	_create_update_einvoice(doc)


def _create_update_einvoice(doc):
	existing_einvoice = frappe.db.exists(
		"eInvoice",
		{
			"sales_invoice": doc.name,
		},
	)

	country = frappe.db.get_value("Company", doc.company, "country") if doc.company else None

	if existing_einvoice:
		einvoice: eInvoice = frappe.get_doc("eInvoice", existing_einvoice)
	else:
		einvoice: eInvoice = frappe.new_doc("eInvoice")

	einvoice.einvoice_type = "Outgoing"
	einvoice.sales_invoice = doc.name
	einvoice.profile = doc.etransaction_profile
	einvoice.country = country
	einvoice.company = doc.company
	einvoice.flags.ignore_permissions = True
	einvoice.save()

	return einvoice
