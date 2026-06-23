"""SuperPDP sandbox self-test.

Provisions the SuperPDP pre-production test recipient ("Tricatel", Peppol address
``0225:315143296_35``) and fires a structured test invoice at the platform, so a
developer can confirm the whole send pipeline end to end from a single button on
a sandbox ``eTransactions Accredited Platform``.

Everything here is idempotent: re-running reuses the existing test customer,
address and routing line and only creates a fresh Sales Invoice to send.
"""

import frappe
from frappe import _

# Tricatel — the SuperPDP pré-production test recipient. In the sandbox the
# routing SIREN (315143296) is shared and each participant gets a suffix; the
# "numéro d'entreprise" (000000001) is the display company number stored on the
# Customer's siren_number, exactly mirroring the seller (Dokompany, _36).
TEST_CUSTOMER_NAME = "Tricatel (SuperPDP Sandbox)"
TEST_SIREN = "000000001"
TEST_DIRECTORY_TYPE = "peppol"
TEST_IDENTIFIER = "0225:315143296_35"
TEST_ADDRESS = {
	"address_line1": "Avenue de la République",
	"city": "Chambray-lès-Tours",
	"pincode": "37170",
	"country": "France",
}
TEST_ITEM_CODE = "SuperPDP Test Service"
TAX_TEMPLATE_TITLE = "TVA 20% Collectée"


def provision_superpdp_test_customer(company: str) -> str:
	"""Create (or refresh) the Tricatel test customer, address and routing line.

	A best-effort directory sync mirrors the real platform data, but correctness
	does not depend on it: the ``0225:315143296_35`` line is guaranteed active and
	set as the customer's default routing line, and the entity type is forced to
	``private`` so the invoice is classified B2B (not e-reported B2C).

	Returns the customer name.
	"""
	customer = _ensure_customer()
	address = _ensure_address(customer)
	_ensure_directory_synced(customer, company)
	line = _ensure_directory_line(customer, address)

	frappe.db.set_value(
		"Customer",
		customer,
		{
			"directory_entity_type": "private",
			"directory_name": "Tricatel",
			"directory_closed": 0,
			"default_directory_line": line,
			# Pin so a later manual/cron sync can't revert the forced routing.
			"directory_pinned": 1,
		},
	)
	return customer


@frappe.whitelist()
def send_superpdp_test_invoice(platform_name: str) -> dict:
	"""Provision the Tricatel test customer and send it a structured test invoice.

	Whitelisted entry point for the "Run sandbox test" button. Only runs against a
	SuperPDP platform flagged as a sandbox. Returns the created records and the
	platform flow id/status.
	"""
	frappe.only_for(("System Manager", "Accounts Manager"))

	platform = frappe.get_doc("eTransactions Accredited Platform", platform_name)
	if platform.platform_type != "SuperPDP":
		frappe.throw(_("The sandbox test is only available for SuperPDP platforms."))
	if not platform.is_sandbox:
		frappe.throw(
			_("Enable 'Pre-production (Sandbox)' on this platform before running the sandbox test.")
		)

	company = platform.company
	customer = provision_superpdp_test_customer(company)
	einvoice = _create_and_send_test_invoice(company, customer)

	return {
		"customer": customer,
		"sales_invoice": einvoice.sales_invoice,
		"einvoice": einvoice.name,
		"flow_id": einvoice.pa_flow_id,
		"pa_status": einvoice.pa_status,
	}


# ---------------------------------------------------------------------------
# Provisioning helpers
# ---------------------------------------------------------------------------


def _ensure_customer() -> str:
	existing = frappe.db.get_value("Customer", {"customer_name": TEST_CUSTOMER_NAME}, "name")
	if existing:
		frappe.db.set_value(
			"Customer", existing, {"siren_number": TEST_SIREN, "directory_type": TEST_DIRECTORY_TYPE}
		)
		return existing

	customer = frappe.get_doc({
		"doctype": "Customer",
		"customer_name": TEST_CUSTOMER_NAME,
		"customer_type": "Company",
		"siren_number": TEST_SIREN,
		"directory_type": TEST_DIRECTORY_TYPE,
		"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
		"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
	})
	customer.insert(ignore_permissions=True)
	return customer.name


def _ensure_address(customer: str) -> str:
	address_name = frappe.db.get_value(
		"Dynamic Link",
		{"parenttype": "Address", "link_doctype": "Customer", "link_name": customer},
		"parent",
	)
	if address_name:
		return address_name

	address = frappe.get_doc({
		"doctype": "Address",
		"address_title": TEST_CUSTOMER_NAME,
		"address_type": "Billing",
		"is_primary_address": 1,
		**TEST_ADDRESS,
		"links": [{"link_doctype": "Customer", "link_name": customer}],
	})
	address.insert(ignore_permissions=True)
	return address.name


def _ensure_directory_synced(customer: str, company: str) -> None:
	"""Best-effort: mirror the live platform directory. Never fatal.

	Skipped once the customer is pinned (set on a prior run) — the forced routing
	below is the source of truth, and syncing a pinned customer is a no-op anyway.
	"""
	if frappe.db.get_value("Customer", customer, "directory_pinned"):
		return
	try:
		from etransactions.plateforme_agreee.directory import sync_customer_directory

		sync_customer_directory(customer, company)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SuperPDP sandbox directory sync failed")


def _ensure_directory_line(customer: str, address: str) -> str:
	"""Upsert the Tricatel routing line and guarantee it is active."""
	from etransactions.plateforme_agreee.routing import parse_directory_identifier

	parsed = parse_directory_identifier(TEST_IDENTIFIER)
	values = {
		"line_status": "active",
		"siren": parsed["siren"],
		"siret": parsed["siret"],
		"routing_code": parsed["routing_code"],
		"line_type": parsed["line_type"],
		"address": address,
	}

	line = frappe.db.get_value(
		"eInvoicing Directory Line", {"customer": customer, "identifier": TEST_IDENTIFIER}, "name"
	)
	if line:
		frappe.db.set_value("eInvoicing Directory Line", line, values)
		return line

	doc = frappe.get_doc({
		"doctype": "eInvoicing Directory Line",
		"customer": customer,
		"identifier": TEST_IDENTIFIER,
		**values,
	})
	doc.insert(ignore_permissions=True)
	return doc.name


# ---------------------------------------------------------------------------
# Invoice helpers
# ---------------------------------------------------------------------------


def _ensure_test_item() -> str:
	if frappe.db.exists("Item", TEST_ITEM_CODE):
		return TEST_ITEM_CODE

	frappe.get_doc({
		"doctype": "Item",
		"item_code": TEST_ITEM_CODE,
		"item_name": TEST_ITEM_CODE,
		"item_group": "All Item Groups",
		"is_stock_item": 0,
		"is_sales_item": 1,
	}).insert(ignore_permissions=True)
	return TEST_ITEM_CODE


def _resolve_profile() -> str:
	# Use the EN16931 profile: the PPF accredited platform recognises its guideline
	# (BT-24) and applies the French CDV rules on top. The generator adds the French
	# legal mentions and business-process code because the sale is French-domestic.
	for preferred in ("EN16931", "BASIC"):
		if frappe.db.exists("eTransaction Profile", preferred):
			return preferred
	profile = frappe.db.get_value("eTransaction Profile", {}, "name")
	if not profile:
		frappe.throw(
			_("No eTransaction Profile found. Create one (e.g. EN16931) before running the sandbox test.")
		)
	return profile


def _resolve_tax_template(company: str) -> str | None:
	abbr = frappe.db.get_value("Company", company, "abbr")
	template = f"{TAX_TEMPLATE_TITLE} - {abbr}"
	return template if frappe.db.exists("Sales Taxes and Charges Template", template) else None


def _create_and_send_test_invoice(company: str, customer: str):
	"""Create, submit, generate Factur-X for and send a test Sales Invoice."""
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	item = _ensure_test_item()
	profile = _resolve_profile()
	address = frappe.db.get_value(
		"Dynamic Link",
		{"parenttype": "Address", "link_doctype": "Customer", "link_name": customer},
		"parent",
	)

	si = frappe.new_doc("Sales Invoice")
	si.company = company
	si.customer = customer
	si.customer_address = address
	si.posting_date = frappe.utils.today()
	si.etransaction_profile = profile
	si.append("items", {"item_code": item, "qty": 1, "rate": 100.0})

	tax_template = _resolve_tax_template(company)
	if tax_template:
		si.taxes_and_charges = tax_template
		for row in get_taxes_and_charges("Sales Taxes and Charges Template", tax_template):
			si.append("taxes", row)

	si.flags.ignore_permissions = True
	si.insert(ignore_permissions=True)
	si.submit()

	# The eInvoice is created on draft save (on_update); fall back to creating it
	# explicitly, then generate the Factur-X PDF deterministically.
	from etransactions.overrides.sales_invoice import _create_update_einvoice

	einvoice_name = frappe.db.get_value("eInvoice", {"sales_invoice": si.name}, "name")
	if einvoice_name:
		einvoice = frappe.get_doc("eInvoice", einvoice_name)
	else:
		einvoice = _create_update_einvoice(si)

	from etransactions.utils.facturx_pdf import FacturXPDFGenerator

	FacturXPDFGenerator(si.name).attach_to_invoice()

	einvoice.reload()
	einvoice.send_to_plateform()
	einvoice.reload()
	return einvoice
