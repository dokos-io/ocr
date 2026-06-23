from typing import TYPE_CHECKING
import frappe

from frappe import _

from etransactions.utils import EInvoiceProfile


if TYPE_CHECKING:
	from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice
	from etransactions.etransactions.doctype.etransactions_settings.etransactions_settings import eTransactionsSettings
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice


def on_validate(doc, method):
	if not doc.etransaction_profile:
		return

	# Mutations first so the readiness evaluation sees the final values.
	_apply_address_buyer_reference(doc)

	from etransactions.plateforme_agreee.session import get_platform_settings
	if get_platform_settings(doc.company):
		customer_entity_type = frappe.db.get_value("Customer", doc.customer, "directory_entity_type")
		if customer_entity_type == "public":
			_apply_b2g(doc)

	# Single source of truth for all e-invoice warnings (shared with the live
	# in-form panel via check_invoice_readiness).
	from etransactions.plateforme_agreee.readiness import evaluate_einvoice_readiness, INDICATOR
	for finding in evaluate_einvoice_readiness(doc):
		frappe.msgprint(
			finding.detail or finding.label,
			indicator=INDICATOR.get(finding.severity, "orange"),
			alert=True,
		)


def on_update(doc, method):
	"""Create EDocument when Sales Invoice is saved (if profile setting enabled)."""
	if not doc.name or not doc.etransaction_profile:
		return

	if doc.docstatus == 1:
		return

	_create_update_einvoice(doc)


def on_submit(doc, method):
	"""Generate FacturX PDF and submit to accredited platform when a Sales Invoice is submitted."""
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

	# accredited platform submission
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
						_("Could not submit to accredited platform. Please check the error log."),
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
def send_to_plateform(sales_invoice: str):
	"""Manually submit the eInvoice linked to this Sales Invoice to the accredited platform."""
	frappe.get_doc("Sales Invoice", sales_invoice).check_permission("submit")
	einvoice_name = frappe.db.get_value("eInvoice", {"sales_invoice": sales_invoice}, "name")
	if not einvoice_name:
		frappe.throw(_("No eInvoice found for Sales Invoice {0}").format(sales_invoice))
	frappe.get_doc("eInvoice", einvoice_name).send_to_plateform()


@frappe.whitelist(methods=["POST"])
def refresh_pa_status(sales_invoice: str):
	"""Refresh the accredited platform flow status for the eInvoice linked to this Sales Invoice."""
	frappe.get_doc("Sales Invoice", sales_invoice).check_permission("read")
	einvoice_name = frappe.db.get_value("eInvoice", {"sales_invoice": sales_invoice}, "name")
	if not einvoice_name:
		frappe.throw(_("No eInvoice found for Sales Invoice {0}").format(sales_invoice))
	frappe.get_doc("eInvoice", einvoice_name).refresh_pa_status()


def _apply_b2g(doc):
	"""Apply B2G (public-sector / Chorus Pro) handling to a Sales Invoice.

	When the buyer is a public entity, the invoice must carry the French CTC-FR
	profile and the mandatory public-procurement references. We upgrade the
	profile (only from the French regulated profiles) and warn when the code
	service (BT-10 Buyer Reference) is missing.
	"""
	current = doc.etransaction_profile
	if current in (EInvoiceProfile.EN16931.value, EInvoiceProfile.EXTENDED.value):
		doc.etransaction_profile = EInvoiceProfile.CTC_FR.value
		frappe.msgprint(
			_("This customer is a public entity (B2G): the e-invoice profile has been set to "
			  "<b>EXTENDED CTC-FR</b> to comply with Chorus Pro / PPF requirements."),
			alert=True,
			indicator="blue",
		)
	# The missing B2G service-code warning is raised by evaluate_einvoice_readiness.


def _apply_address_buyer_reference(doc):
	"""Let the establishment (customer address) override the customer-level BT-10
	service code. The customer-level value (fetched client-side) remains the
	default when the address carries none."""
	if not doc.customer_address:
		return
	addr_ref = frappe.db.get_value("Address", doc.customer_address, "etransactions_buyer_reference")
	if addr_ref:
		doc.etransactions_buyer_reference = addr_ref


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

	# B2G (public-entity buyer) → set the B2G processing rule for the platform.
	customer_entity_type = frappe.db.get_value("Customer", doc.customer, "directory_entity_type")
	if customer_entity_type == "public":
		einvoice.pa_processing_rule = "B2G"

	# Resolve the routing line for the invoice's establishment unless the user
	# has picked one manually.
	if not einvoice.pa_directory_line:
		from etransactions.plateforme_agreee.routing import resolve_routing
		line = resolve_routing("Customer", doc.customer, doc.customer_address)
		if line:
			einvoice.pa_directory_line = line

	einvoice.flags.ignore_permissions = True
	einvoice.save()

	return einvoice
