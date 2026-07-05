# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Single source of truth for the CTC flow classification of a transaction.

Every in-scope French transaction falls into exactly one regulated flow. The two
legs of the reform — structured e-invoicing (B2B/B2G, routed through the
accredited platform) and e-reporting (B2C and international B2B, declared as
aggregated data to the PPF) — must agree on *which* flow a given sale/purchase
belongs to, or an invoice could be both sent and double-declared.

:func:`classify_transaction` returns that single :class:`TransactionClass` from
the buyer's directory status, type and country. :func:`is_einvoicing_required`
adds the seller-side gate (mirrors akretion's ``fr_einvoicing_required`` /
``_fr_ctc_is_vat_registered``): a structured invoice is only *mandatory* when the
seller company is itself in the reform's scope.

Consumers (keep them thin — never re-derive the class):
* :mod:`etransactions.overrides.sales_invoice` — picks the eInvoice processing
  rule and decides whether to route a structured invoice.
* :mod:`etransactions.plateforme_agreee.ereporting` — decides whether a sale is
  e-reported instead.
* :mod:`etransactions.plateforme_agreee.readiness` — surfaces the determination.
"""

from enum import Enum

import frappe


class TransactionClass(str, Enum):
	"""The regulated flow a transaction belongs to.

	The values of the e-invoiced classes match the ``pa_processing_rule`` stored
	on the eInvoice, so mapping is a straight cast.
	"""

	B2B_DOMESTIC = "B2B"  # FR registered business buyer -> structured e-invoice (CTC)
	B2G = "B2G"  # public-sector buyer -> structured e-invoice (Chorus Pro / PPF)
	B2C = "B2C"  # individual / non-established -> e-reporting
	B2BI = "B2Bi"  # foreign business -> international B2B e-reporting
	OUT_OF_SCOPE = "OutOfScope"  # not a regulated flow


# Classes that are sent to the accredited platform as a structured invoice.
EINVOICED = (TransactionClass.B2B_DOMESTIC, TransactionClass.B2G)
# Classes that are declared to the PPF as e-reporting data.
EREPORTED = (TransactionClass.B2C, TransactionClass.B2BI)


def is_vat_registered(company: str) -> bool:
	"""True when the company is a French entity within the CTC reform's scope.

	Proxied by the presence of a SIREN: a French-registered business is subject to
	the reform. The VAT number (``tax_id``) is a separate readiness concern — a
	franchise-en-base seller has a SIREN but no VAT number and is still in scope.
	"""
	if not company:
		return False
	return bool(frappe.db.get_value("Company", company, "siren_number"))


def _is_france(country: str | None) -> bool:
	return (country or "").strip().lower() in ("france", "fr")


def classify_transaction(company: str, party_type: str, party: str, address: str | None = None) -> TransactionClass:
	"""Return the regulated flow for a transaction with ``party`` (Customer/Supplier).

	Buyer-side only — independent of whether the *seller* is in scope (use
	:func:`is_einvoicing_required` for that). Resolution mirrors the directory
	semantics:

	* public entity                         -> B2G
	* active private VAT-registered business -> B2B (domestic)
	* FR business pending directory sync     -> B2B (so the two legs never disagree)
	* inactive private VAT-registered entity -> B2C (no reachable routing line)
	* foreign business                       -> B2Bi (international B2B e-reporting)
	* individual / non-established           -> B2C
	"""
	if party_type not in ("Customer", "Supplier"):
		return TransactionClass.OUT_OF_SCOPE

	row = frappe.db.get_value(
		party_type,
		party,
		["directory_entity_type", "siren_number", "tax_id", "customer_type" if party_type == "Customer" else "supplier_type"],
		as_dict=True,
	) or {}
	entity_type = row.get("directory_entity_type")

	if entity_type == "public":
		return TransactionClass.B2G
	if entity_type == "private":
		return TransactionClass.B2B_DOMESTIC
	# A FR business carrying a SIREN but no resolved directory status simply hasn't
	# been synced yet — route as B2B, not B2C, so it isn't mis-declared to the PPF.
	if not entity_type and row.get("siren_number"):
		return TransactionClass.B2B_DOMESTIC
	# Inactive VAT-registered private entity: no active routing line, so it cannot
	# be e-invoiced — falls back to e-reporting.
	if entity_type == "private_inactive":
		return TransactionClass.B2C

	# Not in the French directory: distinguish a foreign business (international
	# B2B e-reporting) from an individual (B2C) using country + business markers.
	country = _resolve_country(party_type, party, address)
	type_field = row.get("customer_type") or row.get("supplier_type")
	is_business = (type_field == "Company") or bool(row.get("tax_id"))
	if country and not _is_france(country) and is_business:
		return TransactionClass.B2BI
	return TransactionClass.B2C


def _resolve_country(party_type: str, party: str, address: str | None) -> str | None:
	"""Country of the transaction's address, falling back to the party's primary."""
	if address:
		country = frappe.db.get_value("Address", address, "country")
		if country:
			return country
	link_field = "customer_primary_address" if party_type == "Customer" else "supplier_primary_address"
	primary = frappe.db.get_value(party_type, party, link_field)
	if primary:
		return frappe.db.get_value("Address", primary, "country")
	return None


def is_einvoicing_required(company: str, transaction_class: TransactionClass) -> bool:
	"""True when a structured e-invoice is *mandatory* for this transaction.

	The seller-side gate akretion expresses as ``fr_einvoicing_required``: a
	structured invoice is only required when the seller company is in the reform's
	scope and the buyer is reachable as a structured (B2B/B2G) flow.
	"""
	return is_vat_registered(company) and transaction_class in EINVOICED
