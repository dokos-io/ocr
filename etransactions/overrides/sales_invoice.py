from typing import TYPE_CHECKING
import frappe

from frappe import _
from frappe.utils.data import date_diff

from etransactions.utils import EInvoiceProfile


if TYPE_CHECKING:
	from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice
	from etransactions.etransactions.doctype.etransactions_settings.etransactions_settings import eTransactionsSettings
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
			and EInvoiceProfile(doc.etransaction_profile) < EInvoiceProfile.EXTENDED
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


def on_submit(doc, method):
	"""Generate and attach a FacturX PDF when a Sales Invoice is submitted."""
	if not doc.etransaction_profile:
		return

	settings: eTransactionsSettings = frappe.get_single("eTransactions Settings")
	if not settings.generate_facturx_on_submit:
		return

	_create_update_einvoice(doc)

	from etransactions.utils.facturx_pdf import FacturXPDFGenerator
	try:
		FacturXPDFGenerator(doc.name).attach_to_invoice()
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("FacturX PDF Generation Failed"))
		if settings.block_submission_on_facturx_failure:
			frappe.throw(
				_("The FacturX PDF could not be generated. Submission has been blocked. Please check the error log.")
			)
		frappe.msgprint(
			_("The FacturX PDF could not be generated. Please check the error log."),
			alert=True,
			indicator="orange",
		)


@frappe.whitelist()
def get_einvoice_status(sales_invoice: str) -> dict:
	"""Return the current eInvoice validation state for a Sales Invoice."""
	frappe.get_doc("Sales Invoice", sales_invoice).check_permission("read")

	data = frappe.db.get_value(
		"eInvoice",
		{"sales_invoice": sales_invoice},
		["name", "validation_errors", "validation_warnings", "payee_iban"],
		as_dict=True,
	)

	if not data:
		return {}

	return {
		"einvoice": data.name,
		"errors": data.validation_errors or "",
		"warnings": data.validation_warnings or "",
		"has_iban": bool(data.payee_iban),
	}


@frappe.whitelist()
def get_facturx_pdf(sales_invoice: str) -> str:
	"""Return the FacturX PDF attachment URL, generating the file on demand if needed."""
	frappe.get_doc("Sales Invoice", sales_invoice).check_permission("read")

	from etransactions.utils.facturx_pdf import FacturXPDFGenerator
	generator = FacturXPDFGenerator(sales_invoice)

	url = generator.get_attachment_url()
	if not url:
		url = generator.attach_to_invoice()

	return url


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
