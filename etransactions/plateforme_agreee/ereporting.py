"""B2C e-reporting capture and classification.

Alongside B2B e-invoicing, in-scope transactions that are *not* routed as
structured invoices — sales to private individuals and to foreign/non-established
parties — must be reported to the PPF as aggregated data (e-reporting). This
module decides which source documents need e-reporting and queues
``eReporting Entry`` rows; the cron jobs in :mod:`flow` batch and submit them.

Only platforms that advertise the ``ereporting`` capability
(:data:`etransactions.plateforme_agreee.session.PLATFORM_CAPABILITIES`) expose
the endpoints, so capture is gated on that flag.
"""

import frappe

from etransactions.plateforme_agreee.session import (
	get_platform_for_company,
	platform_supports,
)

# Z12-012 Annex A transaction category. Goods deliveries (livraisons de biens)
# are the safe default; refine per item type (services -> TPS1) as the catalogue
# gains the goods/services distinction.
DEFAULT_TRANSACTION_CATEGORY = "TLB1"


def ereporting_platform(company: str, transaction_type: str = "sales"):
	"""Return the company's platform doc if it supports e-reporting, else None."""
	platform = get_platform_for_company(company, transaction_type=transaction_type)
	if platform and platform_supports(platform.platform_type, "ereporting"):
		return platform
	return None


def should_ereport_sale(doc) -> bool:
	"""True if a Sales Invoice represents an in-scope sale that needs e-reporting.

	A sale is e-reported (rather than e-invoiced) when the customer is not a
	French registered business reachable through the directory — i.e. a private
	individual or a foreign/non-established party.
	"""
	if doc.get("is_return"):
		return False
	if not ereporting_platform(doc.company, "sales"):
		return False
	entity_type = frappe.db.get_value("Customer", doc.customer, "directory_entity_type")
	# private / public companies are reached as structured B2B/B2G invoices.
	return entity_type not in ("private", "public")


def _tax_subtotals(doc) -> list[dict]:
	"""Per-rate VAT breakdown derived from the document's tax rows.

	For a percentage tax the taxable base is recovered as ``tax / (rate/100)``,
	which avoids having to re-group items by rate. A zero-rate row falls back to
	the document net total.
	"""
	rows: list[dict] = []
	for tax in doc.get("taxes", []):
		rate = float(tax.rate or 0)
		tax_amount = float(tax.tax_amount or 0)
		if rate:
			taxable = round(tax_amount / (rate / 100.0), 2)
		else:
			taxable = float(doc.get("net_total") or 0)
		rows.append({"tax_percent": rate, "taxable_amount": taxable, "tax_total": tax_amount})
	if not rows:
		# No taxes (e.g. VAT-exempt): one zero-rate line carrying the net total.
		rows.append(
			{"tax_percent": 0, "taxable_amount": float(doc.get("net_total") or 0), "tax_total": 0}
		)
	return rows


def capture_sale_transaction(doc) -> str | None:
	"""Queue a transaction e-reporting entry for an in-scope B2C/foreign sale.

	Idempotent: returns the existing entry name if one already exists for the
	Sales Invoice. Best-effort — callers should not let failures block the sale.
	"""
	if not should_ereport_sale(doc):
		return None

	existing = frappe.db.get_value(
		"eReporting Entry",
		{"reference_doctype": "Sales Invoice", "reference_name": doc.name, "kind": "transaction"},
		"name",
	)
	if existing:
		return existing

	entry = frappe.new_doc("eReporting Entry")
	entry.company = doc.company
	entry.kind = "transaction"
	entry.role_code = "SE"
	entry.reference_doctype = "Sales Invoice"
	entry.reference_name = doc.name
	entry.date = doc.posting_date
	entry.currency = doc.currency
	entry.category_code = DEFAULT_TRANSACTION_CATEGORY
	entry.tax_exclusive_amount = float(doc.get("net_total") or 0)
	entry.tax_total = float(doc.get("total_taxes_and_charges") or 0)
	for sub in _tax_subtotals(doc):
		entry.append("subtotals", sub)
	entry.flags.ignore_permissions = True
	entry.insert()
	return entry.name


def capture_sale_payment(payment_entry, reference_name: str, allocated_amount, posting_date) -> str | None:
	"""Queue a payment e-reporting entry for a payment against an e-reported sale.

	Payment data (10.2/10.4) accompanies the transaction data for cash-basis VAT.
	Only captured when the referenced sale was itself e-reported.
	"""
	txn = frappe.db.get_value(
		"eReporting Entry",
		{"reference_doctype": "Sales Invoice", "reference_name": reference_name, "kind": "transaction"},
		["name", "company", "currency", "category_code"],
		as_dict=True,
	)
	if not txn:
		return None

	existing = frappe.db.get_value(
		"eReporting Entry",
		{
			"reference_doctype": "Payment Entry",
			"reference_name": payment_entry.name,
			"kind": "payment",
		},
		"name",
	)
	if existing:
		return existing

	entry = frappe.new_doc("eReporting Entry")
	entry.company = txn.company
	entry.kind = "payment"
	entry.role_code = "SE"
	entry.reference_doctype = "Payment Entry"
	entry.reference_name = payment_entry.name
	entry.date = posting_date
	entry.currency = txn.currency
	entry.append(
		"subtotals",
		{"amount": float(allocated_amount or 0), "category_code": txn.category_code},
	)
	entry.flags.ignore_permissions = True
	entry.insert()
	return entry.name


@frappe.whitelist()
def get_source_ereporting(doctype: str, name: str) -> dict:
	"""Return the transaction e-reporting entry for a source document, if any.

	Used by the source-document form to show an e-reporting status indicator.
	"""
	frappe.get_doc(doctype, name).check_permission("read")
	entry = frappe.db.get_value(
		"eReporting Entry",
		{"reference_doctype": doctype, "reference_name": name, "kind": "transaction"},
		["name", "kind", "state", "pa_entry_id"],
		as_dict=True,
	)
	return entry or {}


def on_company_update(doc, method=None):
	"""Doc event: push the VAT regime to the platform when it changes (best-effort)."""
	if not doc.get("etransactions_vat_regime"):
		return
	if not doc.has_value_changed("etransactions_vat_regime"):
		return
	try:
		push_vat_regime(doc.name)
	except Exception:
		frappe.log_error(
			title="e-reporting VAT regime push failed",
			reference_doctype="Company",
			reference_name=doc.name,
		)


def push_vat_regime(company: str) -> None:
	"""Push the company's configured VAT regime to its e-reporting platform.

	No-op when the company has no e-reporting-capable platform or no regime set.
	Raises on transport failure so callers can surface/log it.
	"""
	regime = frappe.db.get_value("Company", company, "etransactions_vat_regime")
	if not regime or not ereporting_platform(company, "sales"):
		return
	from etransactions.plateforme_agreee.session import get_client

	client = get_client(company, transaction_type="sales")
	client.update_vat_regime(regime)
