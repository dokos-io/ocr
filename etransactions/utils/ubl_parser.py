"""
UBL 2.x parser for eInvoice

Parses UBL Invoice / CreditNote / DebitNote XML and populates an
:class:`~etransactions.etransactions.doctype.einvoice.einvoice.eInvoice`
document in place — mirroring what the drafthorse-based
:class:`~etransactions.etransactions.doctype.einvoice.parser.eInvoiceParser`
does for FacturX/CII documents.

Supported customisation IDs (mapped to EInvoiceProfile):
  - PEPPOL BIS Billing 3.0  → EN16931
  - XRechnung 3.x           → XRECHNUNG
  - Plain EN16931            → EN16931
  - Anything else            → EN16931 (safe default)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import frappe
from frappe import _
from lxml import etree as ET

if TYPE_CHECKING:
	from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice


# ---------------------------------------------------------------------------
# UBL 2.x namespaces
# ---------------------------------------------------------------------------

UBL_NAMESPACES = {
	"ubl-inv":  "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
	"ubl-cn":   "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
	"ubl-dn":   "urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2",
	"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
	"cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}

# CustomizationID → EInvoiceProfile value
_CUSTOMIZATION_PROFILE_MAP = {
	"urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0": "EN16931",
	"urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0":      "FACTUR-X",  # XRECHNUNG
	"urn:cen.eu:en16931:2017":                                                     "EN16931",
}

# Document types and their line/quantity element names
_DOC_TYPE_ELEMENTS = {
	"Invoice":    {"line": "InvoiceLine",    "quantity": "InvoicedQuantity"},
	"CreditNote": {"line": "CreditNoteLine", "quantity": "CreditedQuantity"},
	"DebitNote":  {"line": "DebitNoteLine",  "quantity": "DebitedQuantity"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(element, xpath: str, ns: dict | None = None) -> str | None:
	"""Return stripped text of the first matching element, or None."""
	if element is None:
		return None
	found = element.find(xpath, ns or UBL_NAMESPACES)
	return found.text.strip() if found is not None and found.text else None


def _flt(value) -> float | None:
	try:
		return float(value) if value is not None else None
	except (ValueError, TypeError):
		return None


def _detect_doc_type(root) -> str:
	tag = root.tag
	for doc_type in ("Invoice", "CreditNote", "DebitNote"):
		if tag.endswith(f"}}{doc_type}"):
			return doc_type
	return "Invoice"


def _detect_profile(root) -> str:
	customization_id = _text(root, ".//cbc:CustomizationID")
	return _CUSTOMIZATION_PROFILE_MAP.get(customization_id or "", "EN16931")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_ubl(xml_bytes: bytes, einvoice_doc: "eInvoice") -> None:
	"""Parse *xml_bytes* as a UBL 2.x invoice and populate *einvoice_doc* fields."""
	root = ET.fromstring(xml_bytes)

	doc_type = _detect_doc_type(root)
	elements = _DOC_TYPE_ELEMENTS.get(doc_type, _DOC_TYPE_ELEMENTS["Invoice"])

	einvoice_doc.profile = _detect_profile(root)
	einvoice_doc.is_return = 1 if doc_type == "CreditNote" else 0

	# Basic header
	einvoice_doc.id       = _text(root, ".//cbc:ID")
	einvoice_doc.issue_date = _text(root, ".//cbc:IssueDate")
	einvoice_doc.currency = _text(root, ".//cbc:DocumentCurrencyCode")

	if doc_type == "Invoice":
		einvoice_doc.due_date = _text(root, ".//cbc:DueDate")

	# For credit notes, try to set return_against
	if doc_type == "CreditNote":
		billing_ref = _text(
			root, ".//cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID"
		)
		if billing_ref and frappe.db.exists("Purchase Invoice", billing_ref):
			einvoice_doc.return_against = billing_ref

	# Seller (supplier)
	_parse_seller(root, einvoice_doc)

	# Buyer (company)
	_parse_buyer(root, einvoice_doc)

	# Buyer reference / Purchase Order
	order_ref    = _text(root, ".//cac:OrderReference/cbc:ID")
	buyer_ref    = _text(root, ".//cbc:BuyerReference")
	einvoice_doc.buyer_reference = buyer_ref or order_ref or None
	po_candidate = order_ref or buyer_ref
	if (
		po_candidate
		and not einvoice_doc.purchase_order
		and frappe.db.exists("Purchase Order", po_candidate)
	):
		einvoice_doc.purchase_order = po_candidate

	# Line items
	einvoice_doc.items = []
	for line in root.findall(f".//cac:{elements['line']}", UBL_NAMESPACES):
		_parse_line_item(line, einvoice_doc, elements["quantity"])

	# Taxes
	einvoice_doc.taxes = []
	_parse_taxes(root, einvoice_doc)

	# Payment terms
	einvoice_doc.payment_terms = []
	_parse_payment_terms(root, einvoice_doc)

	# Monetary totals
	_parse_monetary_totals(root, einvoice_doc)

	# Bank details
	_parse_bank_details(root, einvoice_doc)

	# Billing period
	_parse_billing_period(root, einvoice_doc)


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------

def _parse_seller(root, doc: "eInvoice") -> None:
	party = root.find(".//cac:AccountingSupplierParty/cac:Party", UBL_NAMESPACES)
	if party is None:
		return

	doc.seller_name = (
		_text(party, ".//cac:PartyLegalEntity/cbc:RegistrationName")
		or _text(party, ".//cac:PartyName/cbc:Name")
	)
	doc.seller_tax_id = _text(party, ".//cac:PartyTaxScheme/cbc:CompanyID")

	endpoint = party.find(".//cbc:EndpointID", UBL_NAMESPACES)
	if endpoint is not None:
		doc.seller_electronic_address        = (endpoint.text or "").strip() or None
		doc.seller_electronic_address_scheme = endpoint.get("schemeID") or None

	_parse_address(party, doc, "seller")


def _parse_buyer(root, doc: "eInvoice") -> None:
	party = root.find(".//cac:AccountingCustomerParty/cac:Party", UBL_NAMESPACES)
	if party is None:
		return

	doc.buyer_name = (
		_text(party, ".//cac:PartyLegalEntity/cbc:RegistrationName")
		or _text(party, ".//cac:PartyName/cbc:Name")
	)
	doc.buyer_tax_id = _text(party, ".//cac:PartyTaxScheme/cbc:CompanyID")

	endpoint = party.find(".//cbc:EndpointID", UBL_NAMESPACES)
	if endpoint is not None:
		doc.buyer_electronic_address        = (endpoint.text or "").strip() or None
		doc.buyer_electronic_address_scheme = endpoint.get("schemeID") or None

	_parse_address(party, doc, "buyer")


def _parse_address(party, doc: "eInvoice", prefix: str) -> None:
	addr = party.find(".//cac:PostalAddress", UBL_NAMESPACES)
	if addr is None:
		return

	country_code = _text(addr, ".//cac:Country/cbc:IdentificationCode")
	country = (
		frappe.db.get_value("Country", {"code": country_code.lower()}, "name")
		if country_code
		else None
	)

	doc.set(f"{prefix}_address_line_1", _text(addr, ".//cbc:StreetName"))
	doc.set(f"{prefix}_address_line_2", _text(addr, ".//cbc:AdditionalStreetName"))
	doc.set(f"{prefix}_city",           _text(addr, ".//cbc:CityName"))
	doc.set(f"{prefix}_postcode",       _text(addr, ".//cbc:PostalZone"))
	doc.set(f"{prefix}_country",        country)


def _parse_line_item(line, doc: "eInvoice", quantity_elem: str) -> None:
	item = doc.append("items")

	product_name = _text(line, ".//cac:Item/cbc:Name")
	product_description = _text(line, ".//cac:Item/cbc:Description")

	if product_name and len(product_name) > 140:
		item.product_name        = product_name[:140]
		item.product_description = product_name + (" | " + product_description if product_description else "")
	else:
		item.product_name        = product_name
		item.product_description = product_description

	item.seller_product_id = _text(line, ".//cac:Item/cac:SellersItemIdentification/cbc:ID")
	buyer_item_id          = _text(line, ".//cac:Item/cac:BuyersItemIdentification/cbc:ID")

	if buyer_item_id and frappe.db.exists("Item", buyer_item_id):
		item.item = buyer_item_id
	else:
		item.item = None

	# Quantity / UOM
	qty_el = line.find(f".//cbc:{quantity_elem}", UBL_NAMESPACES)
	if qty_el is not None and qty_el.text:
		item.billed_quantity = _flt(qty_el.text)
		item.unit_code       = qty_el.get("unitCode") or None

	# Rate
	price_text = _text(line, ".//cac:Price/cbc:PriceAmount")
	if price_text is not None:
		basis_qty = float(item.billed_quantity or 1) or 1.0
		item.net_rate = _flt(price_text) / basis_qty if item.billed_quantity else _flt(price_text)

	# Line total
	item.total_amount = _flt(_text(line, ".//cbc:LineExtensionAmount"))

	# Tax rate (informational)
	tax_category = line.find(".//cac:Item/cac:ClassifiedTaxCategory", UBL_NAMESPACES)
	if tax_category is not None:
		item.tax_rate = _flt(_text(tax_category, ".//cbc:Percent"))


def _parse_taxes(root, doc: "eInvoice") -> None:
	tax_total = root.find(".//cac:TaxTotal", UBL_NAMESPACES)
	if tax_total is None:
		return

	for subtotal in tax_total.findall(".//cac:TaxSubtotal", UBL_NAMESPACES):
		t = doc.append("taxes")
		t.basis_amount          = _flt(_text(subtotal, ".//cbc:TaxableAmount"))
		t.calculated_amount     = _flt(_text(subtotal, ".//cbc:TaxAmount"))

		tax_cat = subtotal.find(".//cac:TaxCategory", UBL_NAMESPACES)
		if tax_cat is not None:
			t.rate_applicable_percent = _flt(_text(tax_cat, ".//cbc:Percent"))


def _parse_payment_terms(root, doc: "eInvoice") -> None:
	for pt in root.findall(".//cac:PaymentTerms", UBL_NAMESPACES):
		amount_text = _text(pt, ".//cbc:Amount")
		if not amount_text:
			# Simple due-date-only term
			due = _text(pt, ".//cbc:PaymentDueDate")
			if due and not doc.due_date:
				doc.due_date = due
			continue

		t = doc.append("payment_terms")
		t.due            = _text(pt, ".//cbc:PaymentDueDate") or doc.due_date
		t.partial_amount = _flt(amount_text)
		t.description    = _text(pt, ".//cbc:Note")

		discount_terms = pt.find(".//cac:PaymentDiscountTerms", UBL_NAMESPACES)
		if discount_terms is not None:
			t.discount_basis_date          = _text(discount_terms, ".//cbc:BasisDate")
			t.discount_calculation_percent = _flt(_text(discount_terms, ".//cbc:CalculationPercent"))
			t.discount_actual_amount       = _flt(_text(discount_terms, ".//cbc:Amount"))


def _parse_monetary_totals(root, doc: "eInvoice") -> None:
	totals = root.find(".//cac:LegalMonetaryTotal", UBL_NAMESPACES)
	if totals is None:
		return

	doc.line_total      = _flt(_text(totals, ".//cbc:LineExtensionAmount"))
	doc.allowance_total = _flt(_text(totals, ".//cbc:AllowanceTotalAmount"))
	doc.charge_total    = _flt(_text(totals, ".//cbc:ChargeTotalAmount"))
	doc.tax_basis_total = _flt(_text(totals, ".//cbc:TaxExclusiveAmount"))
	doc.grand_total     = _flt(_text(totals, ".//cbc:TaxInclusiveAmount"))
	doc.total_prepaid   = _flt(_text(totals, ".//cbc:PrepaidAmount"))
	doc.due_payable     = _flt(_text(totals, ".//cbc:PayableAmount"))

	# tax_total from TaxTotal/TaxAmount (first occurrence)
	tax_total_el = root.find(".//cac:TaxTotal/cbc:TaxAmount", UBL_NAMESPACES)
	if tax_total_el is not None:
		doc.tax_total = _flt(tax_total_el.text)


def _parse_bank_details(root, doc: "eInvoice") -> None:
	payment_means = root.find(".//cac:PaymentMeans", UBL_NAMESPACES)
	if payment_means is None:
		return

	financial_account = payment_means.find(".//cac:PayeeFinancialAccount", UBL_NAMESPACES)
	if financial_account is None:
		return

	doc.payee_iban         = _text(financial_account, ".//cbc:ID") or None
	doc.payee_account_name = _text(financial_account, ".//cbc:Name") or None

	branch = financial_account.find(".//cac:FinancialInstitutionBranch", UBL_NAMESPACES)
	if branch is not None:
		doc.payee_bic = _text(branch, ".//cbc:ID") or None


def _parse_billing_period(root, doc: "eInvoice") -> None:
	period = root.find(".//cac:InvoicePeriod", UBL_NAMESPACES)
	if period is None:
		return

	doc.billing_period_start = _text(period, ".//cbc:StartDate")
	doc.billing_period_end   = _text(period, ".//cbc:EndDate")
