"""Validation guards for the e-invoicing fields on master data.

Customer and Company carry an ``etransactions_electronic_address_scheme`` (a Common
Code) and an ``etransactions_electronic_address`` — the buyer (BT-49) and seller
(BT-34) endpoints. Supplier does not: it is the seller on invoices we *receive*, so
its endpoint is never emitted by anything we generate. The scheme is emitted verbatim
as the EndpointID/@schemeID of every generated eInvoice, where EN16931 rule BR-CL-25
requires it to belong to the CEF EAS code list.

The scheme field is an unfiltered Link to Common Code, whose options span the whole
Peppol participant-identifier-scheme list — a superset of EAS that also includes
Peppol-internal schemes (e.g. 0242 SPIS). Picking one of those produces an eInvoice
that fails validation downstream with an opaque BR-CL-25 message. This guard rejects
a non-EAS scheme at save time, naming the field to fix — and :func:`eas_scheme_query`
keeps the non-EAS schemes out of the picker in the first place.
"""

import frappe
from frappe import _

from etransactions.plateforme_agreee.routing import EAS_CODES, is_valid_eas_scheme


def validate_electronic_address(doc, method=None):
	"""Reject a non-EAS electronic-address scheme on a Customer/Supplier/Company."""
	scheme_name = doc.get("etransactions_electronic_address_scheme")
	if not scheme_name:
		return

	scheme_code = frappe.db.get_value("Common Code", scheme_name, "common_code")
	if is_valid_eas_scheme(scheme_code):
		return

	frappe.throw(
		_(
			"The Electronic Address Scheme {0} is not part of the CEF EAS code list, so "
			"e-invoices addressed with it are rejected by EN16931 (rule BR-CL-25). Choose "
			"a valid scheme — for a French entity use 0225 (FRCTC Electronic Address) or "
			"0009 (SIRET)."
		).format(frappe.bold(scheme_code or scheme_name)),
		title=_("Invalid Electronic Address Scheme"),
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def eas_scheme_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link-field query that offers only CEF EAS Common Codes (BR-CL-25).

	Bound to ``etransactions_electronic_address_scheme`` on Customer and Company
	so the picker can't surface a non-EAS scheme. Shares the EAS allowlist
	with the save-time guard, so the dropdown and the validation never disagree.
	"""
	like = f"%{txt}%"
	return frappe.get_all(
		"Common Code",
		filters=[["common_code", "in", sorted(EAS_CODES)]],
		or_filters=[["common_code", "like", like], ["title", "like", like]] if txt else None,
		fields=["name", "title", "common_code"],
		order_by="common_code asc",
		start=start,
		page_length=page_len,
		as_list=True,
	)


def apply_default_etransaction_profile(doc, method=None):
	"""Default the e-invoicing profile on French B2B customers (Customer.validate).

	The eTransaction Profile is the master switch for the whole pipeline — a
	missing profile silently disables e-invoicing. When eTransactions Settings
	carries a ``default_etransaction_profile``, apply it to customers that look
	like French businesses (SIREN present, primary address French or unset),
	with a message so the change is never silent.
	"""
	if doc.get("etransaction_profile") or not doc.get("siren_number"):
		return

	default_profile = frappe.db.get_single_value(
		"eTransactions Settings", "default_etransaction_profile"
	)
	if not default_profile:
		return

	address = doc.get("customer_primary_address")
	if address and frappe.db.get_value("Address", address, "country") not in (None, "France"):
		return

	doc.etransaction_profile = default_profile
	frappe.msgprint(
		_(
			"The default e-invoicing profile <b>{0}</b> was applied to this customer"
			" (configured in eTransactions Settings)."
		).format(frappe.utils.sanitize_html(default_profile)),
		alert=True,
		indicator="blue",
	)
