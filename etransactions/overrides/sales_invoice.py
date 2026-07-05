from typing import TYPE_CHECKING
import frappe

from frappe import _

from etransactions.utils import EInvoiceProfile


if TYPE_CHECKING:
	from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice
	from etransactions.etransactions.doctype.etransactions_settings.etransactions_settings import eTransactionsSettings
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice


def on_validate(doc, method):
	if doc.etransaction_profile:
		# Mutations first so the readiness evaluation sees the final values.
		_apply_address_buyer_reference(doc)
		_propagate_routing_from_order(doc)

		# Record the regulated-flow determination (single source of truth) so the user
		# can see why an invoice will (or won't) be sent, and apply B2G handling.
		from etransactions.plateforme_agreee.classification import TransactionClass, classify_transaction

		if doc.customer:
			cls = classify_transaction(doc.company, "Customer", doc.customer, doc.customer_address)
			doc.etransactions_flow_class = cls.value

			from etransactions.plateforme_agreee.session import get_platform_settings
			if get_platform_settings(doc.company) and cls == TransactionClass.B2G:
				_apply_b2g(doc)

	# Single source of truth for all e-invoice warnings (shared with the live
	# in-form panel via check_invoice_readiness). Runs even without a profile:
	# a missing profile on a B2B/B2G invoice is itself a finding — otherwise
	# the whole pipeline is silently disabled.
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


def before_submit(doc, method):
	"""Confirmation-time directory sync, honouring the platform's
	``directory_sync_on_submit`` mode (blocking/not_blocking/no), then the
	optional hard gate on blocking e-invoicing findings."""
	if doc.get("customer"):
		from etransactions.plateforme_agreee.directory import maybe_sync_on_confirm

		maybe_sync_on_confirm(doc.company, doc.customer, origin=f"Sales Invoice {doc.name}")

	_block_on_blocking_findings(doc)


def _block_on_blocking_findings(doc):
	"""Server-side submit gate (opt-in via eTransactions Settings).

	The JS confirm can be bypassed (and resolves on error); when
	``block_submission_on_blocking_findings`` is on, submission is refused while
	blocking findings remain, so a rejection is not discovered asynchronously
	after the PA send.
	"""
	if not doc.get("etransaction_profile"):
		return
	if not frappe.db.get_single_value("eTransactions Settings", "block_submission_on_blocking_findings"):
		return

	from etransactions.plateforme_agreee.readiness import evaluate_einvoice_readiness, evaluate_party_readiness

	errors = [f.detail or f.label for f in evaluate_einvoice_readiness(doc) if f.severity == "error"]
	if doc.get("customer"):
		errors += [
			_("{0}: {1}").format(_("Customer"), pf.get("label"))
			for pf in evaluate_party_readiness("Customer", doc.customer)
			if pf.get("severity") == "error"
		]

	if errors:
		items = "".join(f"<li>{e}</li>" for e in errors)
		frappe.throw(
			_(
				"This invoice cannot be submitted while blocking e-invoicing issues remain"
				" (enforced by eTransactions Settings):<ul>{0}</ul>"
			).format(items),
			title=_("E-invoicing readiness"),
		)


def on_submit(doc, method):
	"""Generate FacturX PDF and submit to accredited platform when a Sales Invoice is submitted."""
	# B2C / foreign sales are reported as aggregated data, not structured
	# invoices, so this runs independently of the e-invoice profile.
	_capture_ereporting(doc)

	if not doc.etransaction_profile:
		return

	settings: eTransactionsSettings = frappe.get_single("eTransactions Settings")
	if settings.generate_facturx_on_submit:
		einvoice = _create_update_einvoice(doc)

		# Factur-X embedding is CII-only: a UBL eInvoice is sent as raw XML, so
		# no hybrid PDF is generated (leaving einvoice_embedded_document empty
		# guarantees _get_file_for_pa takes the raw-XML branch).
		if not (einvoice and einvoice.get("syntax") == "UBL"):
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
		from etransactions.plateforme_agreee.classification import EINVOICED, classify_transaction

		cls = classify_transaction(doc.company, "Customer", doc.customer, doc.customer_address)
		if cls in EINVOICED:
			einvoice_name = frappe.db.get_value("eInvoice", {"sales_invoice": doc.name}, "name")
			if not einvoice_name:
				# eInvoice may not exist yet if FacturX was disabled; create it now
				einvoice = _create_update_einvoice(doc)
				einvoice_name = einvoice.name if einvoice else None
			if einvoice_name:
				# Send after commit on the short queue so an unreachable/slow
				# platform can't delay or roll back the invoice submission.
				frappe.enqueue(
					"etransactions.plateforme_agreee.flow.send_einvoice_to_plateforme",
					queue="short",
					enqueue_after_commit=True,
					einvoice_name=einvoice_name,
				)


def before_cancel(doc, method):
	"""Guard cancelling an invoice already transmitted to the accredited platform.

	A local cancel with no 'Cancelled' lifecycle status desyncs the accounting from
	the platform, so direct cancellation is blocked and users are pointed at the
	guided flow (:func:`cancel_with_lifecycle`), which reports the status first.
	"""
	if frappe.flags.etransactions_cancel_confirmed:
		return
	row = _transmitted_einvoice(doc.name)
	if not row:
		return
	frappe.throw(
		_(
			"This invoice was transmitted to the accredited platform (flow {0})."
			" Cancel it from the Sales Invoice form so the 'Cancelled' lifecycle"
			" status is reported to the platform first."
		).format(row.pa_flow_id)
	)


def _transmitted_einvoice(sales_invoice: str):
	"""The Outgoing eInvoice live on the platform for this invoice, if any.

	Errored/rejected flows never entered the buyer's circuit, so they don't
	need a lifecycle status before cancellation.
	"""
	row = frappe.db.get_value(
		"eInvoice",
		{"sales_invoice": sales_invoice, "einvoice_type": "Outgoing"},
		["name", "pa_flow_id", "pa_status"],
		as_dict=True,
	)
	if not row or not row.pa_flow_id or (row.pa_status or "") in ("error", "rejected"):
		return None
	return row


@frappe.whitelist(methods=["POST"])
def cancel_with_lifecycle(sales_invoice: str):
	"""Report the 'Cancelled' lifecycle status to the platform, then cancel.

	The status is sent synchronously: this is a user-initiated action and a
	platform failure must surface before the accounting cancellation happens.
	Platforms that cannot carry the status (SuperPDP has no ``fr:`` code for it)
	are skipped with a note and the invoice is still cancelled.
	"""
	doc = frappe.get_doc("Sales Invoice", sales_invoice)
	doc.check_permission("cancel")

	row = _transmitted_einvoice(sales_invoice)
	if row:
		from etransactions.plateforme_agreee.auto_status import _platform_supports

		if _platform_supports(doc.company, "sales", "cancelled"):
			frappe.get_doc("eInvoice", row.name).submit_lifecycle_status("cancelled")
		else:
			frappe.msgprint(
				_(
					"The accredited platform does not support the 'Cancelled' lifecycle"
					" status: the invoice is cancelled locally only. Inform the buyer"
					" through another channel."
				),
				indicator="orange",
				alert=True,
			)

	frappe.flags.etransactions_cancel_confirmed = True
	try:
		doc.cancel()
	finally:
		frappe.flags.etransactions_cancel_confirmed = False


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
def get_einvoice_panel(sales_invoice: str) -> dict:
	"""Unified post-send e-invoicing state for the Sales Invoice panel.

	Returns the platform status/flow plus the rejection reasons and schematron
	validation issues as fixable findings, so the user can see *why* a send failed
	and *where to fix it* without opening the eInvoice.
	"""
	frappe.get_doc("Sales Invoice", sales_invoice).check_permission("read")

	row = frappe.db.get_value(
		"eInvoice",
		{"sales_invoice": sales_invoice},
		["name", "pa_status", "pa_flow_id"],
		as_dict=True,
	)
	if not row:
		return {"einvoice": None, "pa_status": "", "pa_flow_id": "", "problems": []}

	from etransactions.plateforme_agreee.readiness import findings_from_platform_errors

	return {
		"einvoice": row.name,
		"pa_status": row.pa_status or "",
		"pa_flow_id": row.pa_flow_id or "",
		"problems": findings_from_platform_errors(row.name),
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


def _capture_ereporting(doc):
	"""Best-effort: queue a B2C/foreign sale for PPF e-reporting. Never blocks submit."""
	try:
		from etransactions.plateforme_agreee.ereporting import capture_sale_transaction
		capture_sale_transaction(doc)
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("e-reporting capture failed"))


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


def _propagate_routing_from_order(doc):
	"""Carry a routing line chosen on the source Sales Order onto the invoice.

	Only when the invoice has no line yet and every item comes from a single
	order — a multi-order invoice has no unambiguous establishment, so the
	invoice falls back to resolving routing from the buyer's directory.
	"""
	if doc.get("etransactions_routing_line"):
		return
	orders = {row.sales_order for row in doc.get("items", []) if row.get("sales_order")}
	if len(orders) == 1:
		line = frappe.db.get_value("Sales Order", orders.pop(), "etransactions_routing_line")
		if line:
			doc.etransactions_routing_line = line


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

	# Processing rule from the shared classifier (single source of truth): public
	# -> B2G, registered/pending FR business -> B2B, inactive/individual -> B2C,
	# foreign business -> B2Bi. B2C/B2Bi are e-reported rather than invoiced.
	from etransactions.plateforme_agreee.classification import classify_transaction

	einvoice.pa_processing_rule = classify_transaction(
		doc.company, "Customer", doc.customer, doc.customer_address
	).value

	# Routing line for the invoice's establishment. Prefer a line carried on the
	# invoice (chosen manually or propagated from the source Sales Order), else
	# resolve it from the buyer's directory. A line already on the eInvoice wins.
	if not einvoice.pa_directory_line:
		line = doc.get("etransactions_routing_line")
		if not line:
			from etransactions.plateforme_agreee.routing import resolve_routing
			line = resolve_routing("Customer", doc.customer, doc.customer_address)
		if line:
			einvoice.pa_directory_line = line

	einvoice.flags.ignore_permissions = True
	einvoice.save()

	return einvoice
