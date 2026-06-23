"""Validation guards for the e-invoicing fields on master data.

Customer / Supplier / Company all carry an ``etransactions_electronic_address_scheme``
(a Common Code) and an ``etransactions_electronic_address``. The scheme is emitted
verbatim as the EndpointID/@schemeID (BT-34 / BT-49) of every generated eInvoice,
where EN16931 rule BR-CL-25 requires it to belong to the CEF EAS code list.

The scheme field is an unfiltered Link to Common Code, whose options span the whole
Peppol participant-identifier-scheme list — a superset of EAS that also includes
Peppol-internal schemes (e.g. 0242 SPIS). Picking one of those produces an eInvoice
that fails validation downstream with an opaque BR-CL-25 message. This guard rejects
a non-EAS scheme at save time, naming the field to fix.
"""

import frappe
from frappe import _

from etransactions.plateforme_agreee.routing import is_valid_eas_scheme


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
