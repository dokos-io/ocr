# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Single source of truth for e-invoicing readiness checks.

Two kinds of evaluation share one vocabulary of :class:`Finding`:

* :func:`evaluate_party_readiness` — is a Customer / Supplier ready to be
  invoiced electronically (identity, address, SIRET, routing)? Drives the
  master-data readiness wizard, the FacturX Readiness workspace widget
  (via :func:`customer_check_specs`) and the Customer eInvoice Readiness report.
* :func:`evaluate_einvoice_readiness` — will *this* invoice produce a valid
  e-invoice (seller data, routing line, taxes, payment schedule)? Drives the
  live in-form panel (a dry run on the unsaved doc) and the server-side
  ``on_validate`` warnings, so the two never disagree.

A ``Finding`` carries a short ``label`` (for the compact in-form panel) and an
optional rich ``detail`` (HTML, for desk ``msgprint``), plus a ``fix`` target so
the UI can jump straight to the field or master that needs attention.
"""

from dataclasses import asdict, dataclass
from typing import Callable

import frappe
from frappe import _

from etransactions.utils import EInvoiceProfile

# severity → desk indicator color
INDICATOR = {"error": "red", "warning": "orange", "info": "blue"}

_ADDRESS_SUBFIELDS = ("address_line1", "city", "pincode", "country")


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


@dataclass
class Finding:
	"""A single readiness issue, in the shared status vocabulary."""

	key: str
	severity: str  # "error" | "warning" | "info"
	label: str
	detail: str | None = None  # optional rich HTML for desk msgprint
	fix_field: str | None = None  # field on the current form to scroll to
	fix_doctype: str | None = None  # related master to open
	fix_name: str | None = None

	def as_dict(self) -> dict:
		return asdict(self)


def as_dicts(findings: list[Finding]) -> list[dict]:
	return [f.as_dict() for f in findings]


# ---------------------------------------------------------------------------
# Party check specifications (shared with the aggregate widget + report)
# ---------------------------------------------------------------------------


@dataclass
class CheckSpec:
	"""A party readiness criterion evaluated against a normalized row dict."""

	key: str
	label: str
	blocking: bool
	passes: Callable[[dict], bool]
	fix_field: str | None = None
	# "address" means the fix target is the row's resolved billing address.
	fix_doctype: str | None = None

	def as_result(self, count: int, total: int) -> dict:
		"""Aggregate shape used by the FacturX Readiness workspace widget."""
		return {
			"key": self.key,
			"label": self.label,
			"complete": count,
			"missing": total - count,
			"total": total,
			"pct": round(count / total * 100) if total else 0,
			"blocking": self.blocking,
		}


def customer_check_specs() -> list[CheckSpec]:
	"""Ordered customer readiness checks. Built per request so ``_()`` resolves."""
	return [
		CheckSpec("siren", _("SIREN number"), True, lambda r: bool(r.get("siren_number")), "siren_number"),
		CheckSpec("tax_id", _("Tax ID (TVA)"), True, lambda r: bool(r.get("tax_id")), "tax_id"),
		CheckSpec(
			"contact",
			_("Primary contact"),
			True,
			lambda r: bool(r.get("customer_primary_contact")),
			"customer_primary_contact",
		),
		# Non-blocking: auto-filled from the primary contact once the dedicated
		# einvoice_email field exists.
		CheckSpec("email", _("Contact email"), False, lambda r: bool(r.get("email_id"))),
		CheckSpec(
			"address",
			_("Billing address"),
			True,
			lambda r: bool(r.get("resolved_address")),
			"customer_primary_address",
		),
		CheckSpec("siret", _("SIRET on billing address"), True, _siret_ok, fix_doctype="address"),
		CheckSpec("addr_fields", _("Complete billing address"), True, _addr_fields_ok, fix_doctype="address"),
	]


def supplier_check_specs() -> list[CheckSpec]:
	"""Lighter supplier checks — routing is the buyer's (company's) concern."""
	return [
		CheckSpec("siren", _("SIREN number"), True, lambda r: bool(r.get("siren_number")), "siren_number"),
		CheckSpec("tax_id", _("Tax ID (TVA)"), True, lambda r: bool(r.get("tax_id")), "tax_id"),
		CheckSpec(
			"address",
			_("Primary address"),
			True,
			lambda r: bool(r.get("resolved_address")),
			"supplier_primary_address",
		),
		CheckSpec("siret", _("SIRET on address"), True, _siret_ok, fix_doctype="address"),
	]


def _siret_ok(r: dict) -> bool:
	return bool(r.get("resolved_address")) and bool(r.get("siret_number"))


def _addr_fields_ok(r: dict) -> bool:
	return bool(r.get("resolved_address")) and all(r.get(f) for f in _ADDRESS_SUBFIELDS)


# ---------------------------------------------------------------------------
# Party readiness (single party)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def evaluate_party_readiness(party_type: str, party: str) -> list[dict]:
	"""Return the readiness findings for one Customer / Supplier."""
	if party_type == "Customer":
		row = _customer_row(party)
		specs = customer_check_specs()
	elif party_type == "Supplier":
		row = _supplier_row(party)
		specs = supplier_check_specs()
	else:
		return []

	findings: list[Finding] = []
	for c in specs:
		if c.passes(row):
			continue
		fix_doctype = fix_name = None
		if c.fix_doctype == "address" and row.get("resolved_address"):
			fix_doctype, fix_name = "Address", row["resolved_address"]
		findings.append(
			Finding(
				key=c.key,
				severity="error" if c.blocking else "warning",
				label=c.label,
				fix_field=c.fix_field,
				fix_doctype=fix_doctype,
				fix_name=fix_name,
			)
		)
	return as_dicts(findings)


def party_findings_from_row(row: dict, party_type: str = "Customer") -> list[str]:
	"""Plain-text issue labels for an already-fetched, address-enriched row.

	Used by the Customer eInvoice Readiness report so its bulk query and the
	per-party evaluator apply the very same predicates.
	"""
	specs = customer_check_specs() if party_type == "Customer" else supplier_check_specs()
	return [c.label for c in specs if not c.passes(row)]


def _customer_row(party: str) -> dict:
	row = frappe.db.get_value(
		"Customer",
		party,
		["siren_number", "tax_id", "customer_primary_contact", "email_id", "customer_primary_address"],
		as_dict=True,
	) or {}
	_attach_address(row, "Customer", party, row.get("customer_primary_address"))
	return row


def _supplier_row(party: str) -> dict:
	fields = ["tax_id", "supplier_primary_address"]
	if frappe.get_meta("Supplier").has_field("siren_number"):
		fields.append("siren_number")
	row = frappe.db.get_value("Supplier", party, fields, as_dict=True) or {}
	_attach_address(row, "Supplier", party, row.get("supplier_primary_address"))
	return row


def _attach_address(row: dict, party_type: str, party: str, named_address: str | None) -> None:
	"""Resolve the party's primary billing address and merge its fields in place.

	Resolution: the explicit ``*_primary_address`` link, else any linked Address
	flagged ``is_primary_address``.
	"""
	addr_fields = ("siret_number", *_ADDRESS_SUBFIELDS)
	address_name = named_address
	if not address_name:
		linked = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Address", "link_doctype": party_type, "link_name": party},
			pluck="parent",
		)
		if linked:
			address_name = frappe.db.get_value(
				"Address", {"name": ["in", linked], "is_primary_address": 1, "disabled": 0}, "name"
			)

	row["resolved_address"] = None
	for f in addr_fields:
		row[f] = None

	if not address_name:
		return

	addr = frappe.db.get_value("Address", address_name, addr_fields, as_dict=True)
	if not addr:
		return
	row["resolved_address"] = address_name
	for f in addr_fields:
		row[f] = addr.get(f)


# ---------------------------------------------------------------------------
# Invoice readiness (this document)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def check_invoice_readiness(doc) -> list[dict]:
	"""Dry-run readiness for an in-memory (possibly unsaved) invoice.

	Combines invoice-level findings with the party's master-data readiness, so
	the form can flag problems *as the user builds the invoice* — no persisted
	eInvoice required. Party findings point Fix at the party master.
	"""
	if isinstance(doc, str):
		doc = frappe.parse_json(doc)
	invoice = frappe.get_doc(doc)
	invoice.flags.ignore_mandatory = True

	result: list[dict] = []
	party_type = party = None
	if invoice.doctype == "Sales Invoice":
		result += as_dicts(evaluate_einvoice_readiness(invoice))
		party_type, party = "Customer", invoice.get("customer")
	elif invoice.doctype == "Purchase Invoice":
		party_type, party = "Supplier", invoice.get("supplier")

	if party:
		for pf in evaluate_party_readiness(party_type, party):
			if not pf.get("fix_doctype"):
				pf["fix_doctype"], pf["fix_name"], pf["fix_field"] = party_type, party, None
			pf["label"] = _("{0}: {1}").format(_(party_type), pf["label"])
			result.append(pf)
	return result


def evaluate_einvoice_readiness(doc) -> list[Finding]:
	"""Findings for a Sales Invoice (extensible to Purchase Invoice).

	Pure: never mutates ``doc``. Safe to run on an unsaved, in-memory doc — it
	resolves routing via :func:`resolve_routing` rather than relying on a
	persisted eInvoice.
	"""
	if getattr(doc, "doctype", None) != "Sales Invoice":
		return []
	if not doc.get("etransaction_profile"):
		return []

	findings: list[Finding] = []
	findings += _seller_findings(doc)
	findings += _routing_findings(doc)
	findings += _tax_findings(doc)
	findings += _payment_schedule_findings(doc)
	return findings


def _seller_findings(doc) -> list[Finding]:
	out: list[Finding] = []
	if not doc.get("company"):
		return out
	company = frappe.utils.sanitize_html(doc.company)

	if not doc.get("company_address"):
		out.append(
			Finding(
				"seller_address",
				"error",
				_("Seller address is missing (BR-08, BR-09)"),
				detail=_(
					"The seller postal address is missing from the e-invoice (rules BR-08, BR-09). "
					"Select a <b>Company Address</b> on this invoice, or add a default address to your company "
					"in <a href='/app/company/{0}'>Company settings</a>."
				).format(company),
				fix_field="company_address",
			)
		)

	company_siren = frappe.db.get_value("Company", doc.company, "siren_number")
	if not doc.get("company_tax_id") and not company_siren:
		out.append(
			Finding(
				"seller_tax_id",
				"error",
				_("Seller tax ID is missing (BR-S-02)"),
				detail=_(
					"The seller tax identification number is missing from the e-invoice (rules BR-S-02, BR-CO-26). "
					"Add a <b>Tax ID</b> (VAT/TVA intracommunautaire) in <a href='/app/company/{0}'>Company settings</a>, "
					"or a <b>SIREN number</b> (numéro SIREN) in the same page."
				).format(company),
			)
		)

	if doc.get("customer_address"):
		address_country = frappe.db.get_value("Address", doc.customer_address, "country")
		if not address_country:
			out.append(
				Finding(
					"buyer_country",
					"error",
					_("Buyer address has no country (BR-09)"),
					detail=_(
						"The buyer address has no country set (rule BR-09). "
						"Add a country to the address <a href='/app/address/{0}'>{0}</a>."
					).format(frappe.utils.sanitize_html(doc.customer_address)),
					fix_doctype="Address",
					fix_name=doc.customer_address,
				)
			)

	if not _seller_has_electronic_address(doc):
		out.append(
			Finding(
				"seller_electronic_address",
				"error",
				_("Seller electronic address is missing (BT-34)"),
				detail=_(
					"The seller electronic address (BT-34) will be missing from the e-invoice, "
					"which is required by the accredited platform (e.g. SuperPDP). "
					"Fix this by doing one of the following:<br><br>"
					"<b>Option 1</b> — Add an <b>Email</b> to your company in "
					"<a href='/app/company/{0}'>Company settings</a>.<br>"
					"<b>Option 2</b> — Set a <b>Company Contact</b> on this invoice with an email address.<br>"
					"<b>Option 3</b> — Configure <b>Electronic Address Scheme</b> and <b>Electronic Address</b> "
					"on the Company record (e.g. SIREN with scheme 0002)."
				).format(company),
			)
		)
	return out


def _seller_has_electronic_address(doc) -> bool:
	company_doc = frappe.db.get_value(
		"Company",
		doc.company,
		["etransactions_electronic_address_scheme", "etransactions_electronic_address", "email"],
		as_dict=True,
	)
	if company_doc:
		if company_doc.etransactions_electronic_address_scheme and company_doc.etransactions_electronic_address:
			return True
		if company_doc.email:
			return True
	if doc.get("company_contact_person"):
		if frappe.db.get_value("Contact", doc.company_contact_person, "email_id"):
			return True
	return False


def _routing_findings(doc) -> list[Finding]:
	"""Accredited-platform routing checks (only when a platform is configured)."""
	from etransactions.plateforme_agreee.session import get_platform_settings

	out: list[Finding] = []
	if not doc.get("company") or not get_platform_settings(doc.company):
		return out

	entity_type = frappe.db.get_value("Customer", doc.customer, "directory_entity_type") if doc.get("customer") else None
	if entity_type not in ("private", "public"):
		return out

	from etransactions.plateforme_agreee.routing import resolve_routing

	line = resolve_routing("Customer", doc.customer, doc.get("customer_address"))
	if not line:
		out.append(
			Finding(
				"routing_line",
				"warning",
				_("No accredited-platform routing line for this establishment"),
				detail=_(
					"No accredited platform directory line could be resolved for this customer's "
					"establishment. Set a default routing line on the customer, or sync the directory."
				),
			)
		)
	elif frappe.db.get_value("eInvoicing Directory Line", line, "commitment_required") and not doc.get("po_no"):
		out.append(
			Finding(
				"commitment_reference",
				"warning",
				_("Routing requires a commitment reference"),
				detail=_("The selected directory line requires a commitment reference (Customer's Purchase Order No)."),
				fix_field="po_no",
			)
		)

	if entity_type == "public" and not doc.get("etransactions_buyer_reference"):
		out.append(
			Finding(
				"b2g_service_code",
				"warning",
				_("B2G service code (BT-10) is usually required"),
				detail=_(
					"This is a B2G invoice (public entity). The <b>service code</b> (code service exécutant, "
					"BT-10 Buyer Reference) is usually required by Chorus Pro. Set it on the invoice or on the customer."
				),
				fix_field="etransactions_buyer_reference",
			)
		)
	return out


def _tax_findings(doc) -> list[Finding]:
	out: list[Finding] = []
	taxes_label = _(doc.meta.get_label("taxes")) if getattr(doc, "meta", None) else _("Taxes")
	for tax_row in doc.get("taxes") or []:
		if tax_row.charge_type == "On Item Quantity":
			out.append(
				Finding(
					f"tax_qty_{tax_row.idx}",
					"warning",
					_("{0} row #{1}: Type '{2}' is not supported in e-invoice").format(
						taxes_label, tax_row.idx, _(tax_row.charge_type)
					),
				)
			)
		if tax_row.charge_type == "Actual" and EInvoiceProfile(doc.etransaction_profile) < EInvoiceProfile.EXTENDED:
			out.append(
				Finding(
					f"tax_actual_{tax_row.idx}",
					"warning",
					_(
						"{0} row #{1}: The charge type 'Actual' is only supported in the eInvoice profiles "
						"'EXTENDED' and 'FACTUR-X'."
					).format(taxes_label, tax_row.idx),
				)
			)
	return out


def _payment_schedule_findings(doc) -> list[Finding]:
	from frappe.utils.data import date_diff

	out: list[Finding] = []
	ps_label = _(doc.meta.get_label("payment_schedule")) if getattr(doc, "meta", None) else _("Payment Schedule")
	modes_of_payment = set()
	for ps in doc.get("payment_schedule") or []:
		if ps.discount_date and date_diff(ps.discount_date, doc.posting_date) < 0:
			out.append(
				Finding(
					f"discount_date_{ps.idx}",
					"warning",
					_("{0} row #{1}: Discount Date should be after Posting Date").format(ps_label, ps.idx),
				)
			)
		if ps.mode_of_payment:
			modes_of_payment.add(ps.mode_of_payment)

	if len(modes_of_payment) > 1:
		out.append(
			Finding(
				"multiple_modes",
				"warning",
				_("{0}: Only one mode of payment will be considered in the e-invoice.").format(ps_label),
			)
		)

	if doc.get("discount_amount"):
		out.append(
			Finding(
				"doc_discount",
				"warning",
				_("A document level discount is currently not supported in the e-invoice."),
			)
		)
	return out
