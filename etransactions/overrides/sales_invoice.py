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

	# Plateforme Agréée validation warnings
	from etransactions.plateforme_agreee.session import get_platform_settings
	if get_platform_settings(doc.company):
		customer_entity_type = frappe.db.get_value("Customer", doc.customer, "directory_entity_type")
		if customer_entity_type in ("private", "public"):
			einvoice_name = frappe.db.get_value("eInvoice", {"sales_invoice": doc.name}, "name")
			if einvoice_name:
				einvoice_pa_line = frappe.db.get_value("eInvoice", einvoice_name, "pa_directory_line")
				if not einvoice_pa_line:
					frappe.msgprint(
						_("No Plateforme Agréée directory line selected on the eInvoice. Set one before submitting."),
						alert=True,
						indicator="orange",
					)
				elif frappe.db.get_value("eInvoicing Directory Line", einvoice_pa_line, "commitment_required") and not doc.po_no:
					frappe.msgprint(
						_("The selected directory line requires a commitment reference (Customer's Purchase Order No)."),
						alert=True,
						indicator="orange",
					)

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
	"""Generate FacturX PDF and submit to Plateforme Agréée when a Sales Invoice is submitted."""
	if not doc.etransaction_profile:
		return

	settings: eTransactionsSettings = frappe.get_single("eTransactions Settings")
	if settings.generate_facturx_on_submit:
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

	# Plateforme Agréée submission
	from etransactions.plateforme_agreee.session import get_platform_settings
	platform_settings = get_platform_settings(doc.company)
	if platform_settings and platform_settings.auto_send_on_submit:
		customer_entity_type = frappe.db.get_value("Customer", doc.customer, "directory_entity_type")
		if customer_entity_type in ("private", "public"):
			einvoice_name = frappe.db.get_value("eInvoice", {"sales_invoice": doc.name}, "name")
			if not einvoice_name:
				# eInvoice may not exist yet if FacturX was disabled; create it now
				einvoice = _create_update_einvoice(doc)
				einvoice_name = einvoice.name if einvoice else None
			if einvoice_name:
				from etransactions.plateforme_agreee.flow import send_einvoice_to_plateforme
				try:
					send_einvoice_to_plateforme(einvoice_name)
				except Exception:
					frappe.log_error(frappe.get_traceback(), _("PA Submission Failed"))
					frappe.msgprint(
						_("Could not submit to Plateforme Agréée. Please check the error log."),
						alert=True,
						indicator="orange",
					)


@frappe.whitelist()
def get_einvoice_status(sales_invoice: str) -> dict:
	"""Return the current eInvoice validation state and PA status for a Sales Invoice."""
	frappe.get_doc("Sales Invoice", sales_invoice).check_permission("read")

	data = frappe.db.get_value(
		"eInvoice",
		{"sales_invoice": sales_invoice},
		["name", "validation_errors", "validation_warnings", "payee_iban", "pa_status", "pa_flow_id"],
		as_dict=True,
	)

	if not data:
		return {}

	return {
		"einvoice": data.name,
		"errors": data.validation_errors or "",
		"warnings": data.validation_warnings or "",
		"has_iban": bool(data.payee_iban),
		"pa_status": data.pa_status or "",
		"pa_flow_id": data.pa_flow_id or "",
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


@frappe.whitelist(methods=["POST"])
def send_to_plateforme(sales_invoice: str):
	"""Manually submit the eInvoice linked to this Sales Invoice to the Plateforme Agréée."""
	frappe.get_doc("Sales Invoice", sales_invoice).check_permission("submit")
	einvoice_name = frappe.db.get_value("eInvoice", {"sales_invoice": sales_invoice}, "name")
	if not einvoice_name:
		frappe.throw(_("No eInvoice found for Sales Invoice {0}").format(sales_invoice))
	frappe.get_doc("eInvoice", einvoice_name).send_to_plateforme()


@frappe.whitelist(methods=["POST"])
def refresh_pa_status(sales_invoice: str):
	"""Refresh the Plateforme Agréée flow status for the eInvoice linked to this Sales Invoice."""
	frappe.get_doc("Sales Invoice", sales_invoice).check_permission("read")
	einvoice_name = frappe.db.get_value("eInvoice", {"sales_invoice": sales_invoice}, "name")
	if not einvoice_name:
		frappe.throw(_("No eInvoice found for Sales Invoice {0}").format(sales_invoice))
	frappe.get_doc("eInvoice", einvoice_name).refresh_pa_status()


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
