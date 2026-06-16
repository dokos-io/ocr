"""Build the CDAR (Cross Domain Acknowledgement and Response) data dictionary.

CDAR is the AFNOR XML format used to report an invoice lifecycle status on
platforms that do not expose a native event endpoint (Esalink / generic AFNOR).
``build_cdar_data()`` maps an ``eInvoice`` plus a canonical lifecycle status to
the ``MDT-*`` / ``MDG-*`` dictionary consumed by ``pyfrctc.generate_cdar()``.

The mapping is ported from the Odoo reference implementation
``l10n_fr_einvoicing/models/fr_einvoicing_event.py::_prepare_xml_data``.
"""

import frappe
from frappe import _

from etransactions.plateforme_agreee import lifecycle_status

# CDAR guideline identifier for the invoice life-cycle profile.
CDAR_GUIDELINE = "urn.cpro.gouv.fr:1p0:CDV:invoice"

_DT_LONG = "%Y%m%d%H%M%S"  # date format 204
_DT_SHORT = "%Y%m%d"       # date format 102

# ISO 6523 scheme identifiers used in the CDAR party blocks.
_SCHEME_SIREN = "0002"   # legal registration (SIREN) for GlobalID
_SCHEME_SIRET = "0225"   # routing address (SIRET) for the recipient URIID


def _siren(doctype: str, name: str, *, what: str) -> str:
	siren = frappe.db.get_value(doctype, name, "siren_number")
	siren = (siren or "").strip()
	if not siren:
		frappe.throw(
			_("The SIREN number of {0} ({1}) is required to report a lifecycle status but is not set.").format(what, name)
		)
	return siren


def _customer_routing_identifier(customer: str) -> str | None:
	"""Return the identifier of the customer's active e-invoicing directory line."""
	if not customer:
		return None
	return frappe.db.get_value(
		"eInvoicing Directory Line",
		{"customer": customer, "line_status": "active"},
		"identifier",
	)


def build_cdar_data(einvoice, status: str, details: list[dict] | None = None,
		attachments: list[dict] | None = None) -> dict:
	"""Return the ``MDT-*`` dict for ``pyfrctc.generate_cdar()``.

	``einvoice``    : an ``eInvoice`` document (Outgoing = we are the seller,
	                  Incoming = we are the buyer).
	``status``      : a canonical lifecycle status (see ``lifecycle_status``).
	``details``     : optional list of ``{reason_code, reason_text, action_code,
	                  action_text, comment}`` dicts (MDG-37 entries).
	``attachments`` : optional list of ``{bin, filename, mime_type}`` dicts (MDT-96).
	"""
	mdt105, mdt88 = lifecycle_status.to_cdar_codes(status)
	label = lifecycle_status.label(status)

	company = einvoice.company
	company_siren = _siren("Company", company, what=_("your company"))
	company_name = frappe.db.get_value("Company", company, "company_name") or company

	inv_number = einvoice.id
	if not inv_number:
		frappe.throw(_("The invoice number is missing from this eInvoice; cannot report a lifecycle status."))

	inv_date = frappe.utils.getdate(einvoice.issue_date) if einvoice.issue_date else None
	if not inv_date:
		frappe.throw(_("The invoice date is missing from this eInvoice; cannot report a lifecycle status."))
	inv_date_str = inv_date.strftime(_DT_SHORT)

	# Resolve counterparty and roles.
	customer = None
	if einvoice.einvoice_type == "Outgoing":
		# We issued the invoice: we are the seller, the counterparty is the buyer.
		sender_role, recipient_role = "SE", "BY"
		issuer_siren = company_siren
		if einvoice.sales_invoice:
			customer = frappe.db.get_value("Sales Invoice", einvoice.sales_invoice, "customer")
		partner_siren = _siren("Customer", customer, what=_("the customer")) if customer else ""
		partner_name = einvoice.buyer_name or ""
		recipient_routing = _customer_routing_identifier(customer) or einvoice.buyer_electronic_address
		inv_type_code = "381" if (einvoice.sales_invoice and frappe.db.get_value(
			"Sales Invoice", einvoice.sales_invoice, "is_return")) else "380"
	else:
		# We received the invoice: we are the buyer, the counterparty is the seller.
		sender_role, recipient_role = "BY", "SE"
		partner_name = einvoice.seller_name or ""
		# The seller's SIREN is not stored as a dedicated field; best-effort from
		# the electronic address (SIRET scheme 0009 -> first 9 digits = SIREN).
		# TODO: persist the supplier SIREN on the eInvoice during parsing.
		partner_siren = _seller_siren_best_effort(einvoice)
		issuer_siren = partner_siren
		recipient_routing = einvoice.seller_electronic_address
		inv_type_code = "380"

	now = frappe.utils.now_datetime()
	now_str = now.strftime(_DT_LONG)
	identifier = f"{inv_number}_{inv_type_code}_{inv_date_str}#{mdt105}_{now_str}"

	data: dict = {
		"MDT-2": "REGULATED",
		"MDT-3": CDAR_GUIDELINE,
		"MDT-4": identifier,
		"MDT-8": now_str,
		"MDT-21": sender_role,
		"MDT-38": {_SCHEME_SIREN: company_siren},
		"MDT-39": company_name,
		"MDT-40": sender_role,
		"MDT-57": {_SCHEME_SIREN: partner_siren},
		"MDT-58": partner_name,
		"MDT-59": recipient_role,
		"MDT-73": recipient_routing or "",
		"MDT-73-1": _SCHEME_SIRET,
		"MDT-74": False,
		"MDT-77": 23,  # Information — for statuses after transmission
		"MDT-78": now_str,
		"MDT-87": inv_number,
		"MDT-88": mdt88,
		"MDT-91": inv_type_code,
		"MDT-95": now_str,
		"MDT-100": inv_date_str,
		"MDT-105": mdt105,
		"MDT-106": label,
		"MDT-129": {_SCHEME_SIREN: issuer_siren},
		"MDG-37": [],
	}

	for detail in (details or []):
		entry: dict = {}
		if detail.get("reason_code"):
			entry["MDT-113"] = detail["reason_code"]
			entry["MDT-114"] = detail.get("reason_text") or detail["reason_code"]
		if detail.get("action_code"):
			entry["MDT-121"] = detail["action_code"]
			entry["MDT-122"] = detail.get("action_text") or detail["action_code"]
		if detail.get("comment"):
			entry["MDT-126"] = detail["comment"]
		if entry:
			data["MDG-37"].append(entry)

	# Payment characteristics (MDG-43) for payment statuses.
	if status in ("payment_sent", "payment_received") and details:
		characteristics = []
		for detail in details:
			if detail.get("amount") is None:
				continue
			characteristics.append({
				# "MEN" (montant encaissé) is the TypeCode required by the CTC
				# schematron (BR-FR-CDV-14) for payment amounts.
				"MDT-207": "MEN",
				"MDT-209": False,
				"MDT-215": {"float": detail["amount"], "currency": detail.get("currency") or "EUR"},
				"MDT-219": _fmt_date(detail.get("payment_date")),
			})
		if characteristics:
			data["MDG-37"].append({"MDG-43": characteristics})

	if attachments:
		data["MDT-96"] = attachments

	return data


def generate_cdar_flow(einvoice, status: str, details: list[dict] | None = None,
		attachments: list[dict] | None = None) -> tuple[bytes, str]:
	"""Build the CDAR XML bytes and a filename for an eInvoice lifecycle status.

	Shared by the AFNOR and Esalink clients, which submit the CDAR as a flow
	with syntax ``"CDAR"``.
	"""
	try:
		from pyfrctc import generate_cdar
	except ImportError:
		frappe.throw(_("The pyfrctc library is not installed."))

	data = build_cdar_data(einvoice, status, details=details, attachments=attachments)
	cdar_bytes = generate_cdar(data)
	filename = f"CDAR_{einvoice.id}_{status}.xml"
	return cdar_bytes, filename


def _fmt_date(value) -> str | bool:
	if not value:
		return False
	return frappe.utils.getdate(value).strftime(_DT_SHORT)


def _seller_siren_best_effort(einvoice) -> str:
	"""Derive the supplier SIREN from the parsed incoming eInvoice fields."""
	scheme = (einvoice.seller_electronic_address_scheme or "").strip()
	address = (einvoice.seller_electronic_address or "").strip()
	digits = "".join(c for c in address if c.isdigit())
	if scheme in ("0009", "0225") and len(digits) >= 9:
		return digits[:9]
	tax_id_digits = "".join(c for c in (einvoice.seller_tax_id or "") if c.isdigit())
	if len(tax_id_digits) == 9:
		return tax_id_digits
	if len(tax_id_digits) == 14:  # SIRET -> SIREN
		return tax_id_digits[:9]
	frappe.throw(
		_("Could not determine the supplier's SIREN from the incoming invoice; cannot report a lifecycle status.")
	)
