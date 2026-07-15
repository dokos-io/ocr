"""UBL 2.1 (EN16931 + Peppol BIS Billing 3.0) invoice builder.

Sibling of the drafthorse-based CII path in ``generator.py``: consumes the same
mapped eInvoice document produced by ``EInvoiceMapper`` and renders a UBL
Invoice (380/384) or CreditNote (381). Chosen by ``resolve_syntax`` when the
buyer is addressed through the Peppol network.

Divergences from the CII/EXTENDED path (UBL carries only the EN16931 core +
Peppol CIUS):
- Peppol allows a single document note (cbc:Note): terms, incoterm and the
  French mandatory mentions are concatenated with the ``#SUBJECTCODE#`` prefix
  convention.
- No structured instalments: the payment schedule is flattened into one
  cac:PaymentTerms note plus the document-level DueDate.
"""

from lxml import etree

import frappe
from frappe.utils.data import flt, getdate, to_markdown

from etransactions.etransactions.doctype.einvoice.generator import (
	DEFAULT_FR_MENTIONS,
	duty_tax_fee_category_codes,
	payment_means_codes,
	vat_exemption_reason_codes,
)
from etransactions.utils import EInvoiceProfile
from etransactions.utils.ubl_parser import UBL_NAMESPACES
from etransactions.utils.vat import validate_vat_id

CBC = UBL_NAMESPACES["cbc"]
CAC = UBL_NAMESPACES["cac"]
INVOICE_NS = UBL_NAMESPACES["ubl-inv"]
CREDIT_NOTE_NS = UBL_NAMESPACES["ubl-cn"]

PEPPOL_CUSTOMIZATION_ID = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
PEPPOL_PROFILE_ID = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"


def _cbc(parent, tag: str, text, **attrs):
	"""Append a cbc:* child with text; skipped entirely when text is empty."""
	if text is None or text == "":
		return None
	el = etree.SubElement(parent, f"{{{CBC}}}{tag}")
	el.text = str(text)
	for key, value in attrs.items():
		if value not in (None, ""):
			el.set(key, str(value))
	return el


def _cac(parent, tag: str):
	return etree.SubElement(parent, f"{{{CAC}}}{tag}")


def _amount(parent, tag: str, value, currency: str):
	return _cbc(parent, tag, f"{flt(value, 2):.2f}", currencyID=currency)


class UBLGenerator:
	"""Render a mapped eInvoice document as UBL 2.1 / Peppol BIS 3.0 XML."""

	def __init__(
		self,
		profile: EInvoiceProfile,
		einvoice,
		company,
		customer,
		seller_address=None,
		buyer_address=None,
		shipping_address=None,
		seller_contact=None,
		buyer_contact=None,
	):
		self.profile = profile
		self.einvoice = einvoice
		self.company = company
		self.customer = customer
		self.seller_address = seller_address
		self.buyer_address = buyer_address
		self.shipping_address = shipping_address
		self.seller_contact = seller_contact
		self.buyer_contact = buyer_contact
		self.root = None
		self.is_credit_note = bool(einvoice.is_return)
		self.currency = einvoice.currency

	def create_einvoice(self):
		ns = CREDIT_NOTE_NS if self.is_credit_note else INVOICE_NS
		tag = "CreditNote" if self.is_credit_note else "Invoice"
		nsmap = {None: ns, "cbc": CBC, "cac": CAC}
		self.root = etree.Element(f"{{{ns}}}{tag}", nsmap=nsmap)

		self._set_header()
		self._add_invoice_period()
		self._add_order_reference()
		self._add_billing_reference()
		self._add_contract_reference()
		self._set_seller()
		self._set_buyer()
		self._add_delivery()
		self._add_payment_means()
		self._add_payment_terms()
		self._add_tax_total()
		self._add_monetary_total()
		for item in self.einvoice.items:
			self._add_line(item)

	def serialize(self) -> bytes:
		return etree.tostring(
			self.root, xml_declaration=True, encoding="UTF-8", pretty_print=True
		)

	# -- header ----------------------------------------------------------------

	def _set_header(self):
		_cbc(self.root, "CustomizationID", PEPPOL_CUSTOMIZATION_ID)
		# A UBL invoice travels the Peppol network (that is why resolve_syntax
		# picked it), so BT-23 stays the Peppol billing process — the French
		# BR-FR-08 codes apply to PPF (CII) flows only.
		_cbc(self.root, "ProfileID", PEPPOL_PROFILE_ID)
		_cbc(self.root, "ID", self.einvoice.id)
		_cbc(self.root, "IssueDate", getdate(self.einvoice.issue_date).isoformat())
		if not self.is_credit_note and self.einvoice.due_date:
			_cbc(self.root, "DueDate", getdate(self.einvoice.due_date).isoformat())

		if self.is_credit_note:
			_cbc(self.root, "CreditNoteTypeCode", "381")
		else:
			type_code = "384" if self.einvoice.amended_from else "380"
			_cbc(self.root, "InvoiceTypeCode", type_code)

		note = self._document_note()
		if note:
			_cbc(self.root, "Note", note)

		_cbc(self.root, "DocumentCurrencyCode", self.currency)
		if self.einvoice.buyer_reference:
			_cbc(self.root, "BuyerReference", self.einvoice.buyer_reference)

	def _document_note(self) -> str | None:
		"""Peppol allows one document note: concatenate terms, incoterm and the
		French mentions using the ``#SUBJECTCODE#`` prefix convention."""
		segments = []
		if self.einvoice.terms:
			segments.append(f"#ABC#{to_markdown(self.einvoice.terms).strip()}")
		if self.einvoice.incoterm:
			named_place = self.einvoice.named_place or ""
			segments.append(f"#AAR#{f'{self.einvoice.incoterm} {named_place}'.strip()}")
		if self._is_french_domestic():
			mentions = {
				"PMD": self.company.get("etransactions_mention_late_penalty"),
				"PMT": self.company.get("etransactions_mention_recovery_costs"),
				"AAB": self.company.get("etransactions_mention_discount"),
			}
			for subject_code, text in mentions.items():
				segments.append(f"#{subject_code}#{(text or DEFAULT_FR_MENTIONS[subject_code]).strip()}")
		return "\n".join(segments) or None

	def _is_french_domestic(self) -> bool:
		return self.einvoice.seller_country == "France" and self.einvoice.buyer_country == "France"

	def _add_invoice_period(self):
		if not (self.einvoice.billing_period_start or self.einvoice.billing_period_end):
			return
		period = _cac(self.root, "InvoicePeriod")
		if self.einvoice.billing_period_start:
			_cbc(period, "StartDate", getdate(self.einvoice.billing_period_start).isoformat())
		if self.einvoice.billing_period_end:
			_cbc(period, "EndDate", getdate(self.einvoice.billing_period_end).isoformat())

	def _add_order_reference(self):
		if self.einvoice.purchase_order:
			order_ref = _cac(self.root, "OrderReference")
			_cbc(order_ref, "ID", self.einvoice.purchase_order)

	def _add_billing_reference(self):
		# BT-25 preceding invoice: return_against for credit notes, amended_from
		# for corrective invoices (type 384).
		preceding = (
			self.einvoice.return_against if self.is_credit_note else self.einvoice.amended_from
		)
		if not preceding:
			return
		billing_ref = _cac(self.root, "BillingReference")
		doc_ref = _cac(billing_ref, "InvoiceDocumentReference")
		_cbc(doc_ref, "ID", preceding)

	def _add_contract_reference(self):
		if self.einvoice.get("contract_reference"):
			contract = _cac(self.root, "ContractDocumentReference")
			_cbc(contract, "ID", self.einvoice.contract_reference)

	# -- parties ---------------------------------------------------------------

	def _set_seller(self):
		supplier_party = _cac(self.root, "AccountingSupplierParty")
		party = _cac(supplier_party, "Party")

		_cbc(
			party,
			"EndpointID",
			self.einvoice.seller_electronic_address,
			schemeID=self.einvoice.seller_electronic_address_scheme,
		)
		self._add_seller_id(party)
		party_name = _cac(party, "PartyName")
		_cbc(party_name, "Name", self.einvoice.seller_name)
		self._add_postal_address(party, "seller")

		# BT-31 (VAT, scheme VAT) and BT-32 (other tax registration, scheme TAX).
		seller_siren = (self.company.get("siren_number") or "").strip()
		vat_added = False
		if self.einvoice.seller_tax_id:
			raw = self.einvoice.seller_tax_id.strip()
			try:
				self._add_party_tax_scheme(party, validate_vat_id(raw), "VAT")
				vat_added = True
			except ValueError:
				self._add_party_tax_scheme(party, raw, "TAX")
		if seller_siren and (vat_added or not self.einvoice.seller_tax_id):
			self._add_party_tax_scheme(party, seller_siren, "TAX")

		legal = _cac(party, "PartyLegalEntity")
		_cbc(legal, "RegistrationName", self.einvoice.seller_name)
		if seller_siren:
			_cbc(legal, "CompanyID", seller_siren, schemeID="0002")

		self._add_seller_contact(party)

	def _add_seller_id(self, party):
		# The buyer's supplier number for us (same source as the CII seller.id).
		for row in self.customer.supplier_numbers:
			if row.company == self.einvoice.company and row.supplier_number:
				identification = _cac(party, "PartyIdentification")
				_cbc(identification, "ID", row.supplier_number)
				break

	def _add_seller_contact(self, party):
		if self.profile <= EInvoiceProfile.BASIC:
			return
		name = self.seller_contact.full_name if self.seller_contact else None
		email = self.seller_contact.email_id if self.seller_contact else None
		phone = (self.seller_contact.phone if self.seller_contact else None) or self.company.phone_no
		if not (name or email or phone):
			return
		contact = _cac(party, "Contact")
		_cbc(contact, "Name", name)
		_cbc(contact, "Telephone", phone)
		_cbc(contact, "ElectronicMail", email)

	def _set_buyer(self):
		customer_party = _cac(self.root, "AccountingCustomerParty")
		party = _cac(customer_party, "Party")

		_cbc(
			party,
			"EndpointID",
			self.einvoice.buyer_electronic_address,
			schemeID=self.einvoice.buyer_electronic_address_scheme,
		)
		party_name = _cac(party, "PartyName")
		_cbc(party_name, "Name", self.einvoice.buyer_name)
		self._add_postal_address(party, "buyer")

		# BT-48: the buyer carries only a VAT identifier.
		if self.einvoice.buyer_tax_id:
			try:
				self._add_party_tax_scheme(party, validate_vat_id(self.einvoice.buyer_tax_id.strip()), "VAT")
			except ValueError:
				pass

		legal = _cac(party, "PartyLegalEntity")
		_cbc(legal, "RegistrationName", self.einvoice.buyer_name)
		buyer_siren = (self.customer.get("siren_number") or "").strip()
		if buyer_siren:
			_cbc(legal, "CompanyID", buyer_siren, schemeID="0002")

		self._add_buyer_contact(party)

	def _add_buyer_contact(self, party):
		if self.profile <= EInvoiceProfile.BASIC or not self.buyer_contact:
			return
		phone = self.buyer_contact.phone or self.buyer_contact.mobile_no
		if not (self.buyer_contact.full_name or self.buyer_contact.email_id or phone):
			return
		contact = _cac(party, "Contact")
		_cbc(contact, "Name", self.buyer_contact.full_name)
		_cbc(contact, "Telephone", phone)
		_cbc(contact, "ElectronicMail", self.buyer_contact.email_id)

	def _add_party_tax_scheme(self, party, company_id: str, scheme: str):
		tax_scheme_wrapper = _cac(party, "PartyTaxScheme")
		_cbc(tax_scheme_wrapper, "CompanyID", company_id)
		tax_scheme = _cac(tax_scheme_wrapper, "TaxScheme")
		_cbc(tax_scheme, "ID", scheme)

	def _add_postal_address(self, party, prefix: str):
		line_1 = self.einvoice.get(f"{prefix}_address_line_1")
		if not line_1:
			return
		address = _cac(party, "PostalAddress")
		_cbc(address, "StreetName", line_1)
		_cbc(address, "AdditionalStreetName", self.einvoice.get(f"{prefix}_address_line_2"))
		_cbc(address, "CityName", self.einvoice.get(f"{prefix}_city"))
		_cbc(address, "PostalZone", self.einvoice.get(f"{prefix}_postcode"))
		country_code = frappe.db.get_value("Country", self.einvoice.get(f"{prefix}_country"), "code")
		if country_code:
			country = _cac(address, "Country")
			_cbc(country, "IdentificationCode", country_code.upper())

	# -- delivery / payment ----------------------------------------------------

	def _add_delivery(self):
		delivery = _cac(self.root, "Delivery")
		_cbc(delivery, "ActualDeliveryDate", getdate(self.einvoice.issue_date).isoformat())
		if not self.shipping_address:
			return
		location = _cac(delivery, "DeliveryLocation")
		address = _cac(location, "Address")
		_cbc(address, "StreetName", self.shipping_address.address_line1)
		_cbc(address, "AdditionalStreetName", self.shipping_address.address_line2)
		_cbc(address, "CityName", self.shipping_address.city)
		_cbc(address, "PostalZone", self.shipping_address.pincode)
		country_code = frappe.db.get_value("Country", self.shipping_address.country, "code")
		if country_code:
			country = _cac(address, "Country")
			_cbc(country, "IdentificationCode", country_code.upper())

	def _add_payment_means(self):
		code = payment_means_codes.get(
			[("Payment Terms Template", self.einvoice.get("payment_terms_template"))]
		)
		payment_means = _cac(self.root, "PaymentMeans")
		_cbc(payment_means, "PaymentMeansCode", str(code))
		if self.einvoice.payee_iban:
			account = _cac(payment_means, "PayeeFinancialAccount")
			_cbc(account, "ID", self.einvoice.payee_iban)
			_cbc(account, "Name", self.einvoice.payee_account_name)
			if self.einvoice.payee_bic:
				branch = _cac(account, "FinancialInstitutionBranch")
				_cbc(branch, "ID", self.einvoice.payee_bic)

	def _add_payment_terms(self):
		# UBL/Peppol has no structured instalments (divergence vs CII EXTENDED):
		# flatten the schedule into one human-readable note; BT-9 stays the
		# document-level DueDate.
		lines = []
		for ps in self.einvoice.payment_terms:
			if not ps.due:
				continue
			parts = [getdate(ps.due).isoformat()]
			if ps.partial_amount and len(self.einvoice.payment_terms) > 1:
				parts.append(f"{flt(ps.partial_amount, 2):.2f} {self.currency}")
			if ps.discount_calculation_percent and ps.discount_basis_date:
				parts.append(f"escompte {flt(ps.discount_calculation_percent, 2)}%")
			lines.append(" — ".join(parts))
		if not lines:
			return
		terms = _cac(self.root, "PaymentTerms")
		_cbc(terms, "Note", "\n".join(lines))

	# -- taxes / totals / lines --------------------------------------------------

	def _tax_category_code(self, extra_sources=None) -> str:
		return str(
			duty_tax_fee_category_codes.get(
				(extra_sources or [])
				+ [
					("Tax Category", self.einvoice.get("tax_category")),
					("Sales Taxes and Charges Template", self.einvoice.get("taxes_and_charges")),
				]
			)
		)

	def _exemption_reason_code(self) -> str:
		return str(
			vat_exemption_reason_codes.get(
				[
					("Tax Category", self.einvoice.get("tax_category")),
					("Sales Taxes and Charges Template", self.einvoice.get("taxes_and_charges")),
				]
			)
		).upper()

	def _exemption_reason_text(self) -> str | None:
		return vat_exemption_reason_codes.get_description(
			[
				("Tax Category", self.einvoice.get("tax_category")),
				("Sales Taxes and Charges Template", self.einvoice.get("taxes_and_charges")),
			]
		)

	def _add_tax_category(self, parent, category_code: str, percent):
		category = _cac(parent, "TaxCategory")
		_cbc(category, "ID", category_code)
		_cbc(category, "Percent", f"{flt(percent, 2):g}")
		# VAT exemption reason — code (BT-121) and/or text (BT-120) — is required for
		# every category other than S (standard) and Z (zero-rated): EN16931
		# BR-E/AE/G/IC/O-10, and mandatory at document level from the FNFE v1.4.0
		# EXTENDED / CTC-FR profiles (XP Z12-012 V1.4.0). Z must carry no reason.
		if str(category_code) not in ("S", "Z"):
			_cbc(category, "TaxExemptionReasonCode", self._exemption_reason_code())
			reason_text = self._exemption_reason_text()
			if reason_text:
				_cbc(category, "TaxExemptionReason", reason_text)
		scheme = _cac(category, "TaxScheme")
		_cbc(scheme, "ID", "VAT")

	def _add_tax_total(self):
		tax_total = _cac(self.root, "TaxTotal")
		_amount(tax_total, "TaxAmount", self.einvoice.tax_total, self.currency)

		if self.einvoice.taxes:
			for tax in self.einvoice.taxes:
				subtotal = _cac(tax_total, "TaxSubtotal")
				_amount(subtotal, "TaxableAmount", tax.basis_amount, self.currency)
				_amount(subtotal, "TaxAmount", tax.calculated_amount, self.currency)
				category_code = self._tax_category_code([("Account", tax.tax_account)])
				self._add_tax_category(subtotal, category_code, tax.rate_applicable_percent)
		else:
			# A tax breakdown is mandatory (BG-23): 0% fallback like the CII path.
			subtotal = _cac(tax_total, "TaxSubtotal")
			_amount(subtotal, "TaxableAmount", self.einvoice.line_total, self.currency)
			_amount(subtotal, "TaxAmount", 0, self.currency)
			self._add_tax_category(subtotal, self._tax_category_code(), 0)

	def _add_monetary_total(self):
		total = _cac(self.root, "LegalMonetaryTotal")
		_amount(total, "LineExtensionAmount", self.einvoice.line_total, self.currency)
		_amount(total, "TaxExclusiveAmount", self.einvoice.tax_basis_total, self.currency)
		_amount(total, "TaxInclusiveAmount", self.einvoice.grand_total, self.currency)
		if self.einvoice.charge_total:
			# NOTE: document-level "Actual" charges are summed here; if one is
			# ever nonzero the Peppol BR-CO-12 rule also expects matching
			# cac:AllowanceCharge elements — resolve_syntax keeps such invoices
			# on the CII path today.
			_amount(total, "ChargeTotalAmount", self.einvoice.charge_total, self.currency)
		if self.einvoice.total_prepaid:
			_amount(total, "PrepaidAmount", self.einvoice.total_prepaid, self.currency)
		_amount(total, "PayableAmount", self.einvoice.due_payable, self.currency)

	def _add_line(self, item):
		line_tag = "CreditNoteLine" if self.is_credit_note else "InvoiceLine"
		quantity_tag = "CreditedQuantity" if self.is_credit_note else "InvoicedQuantity"
		line = _cac(self.root, line_tag)
		_cbc(line, "ID", str(item.idx))

		# Same sign-flip as the CII path: BR-27 rejects negative prices, so a
		# negative-rate line becomes a positive price with a negative quantity.
		multiplier = -1 if item.net_rate < 0 and item.billed_quantity > 0 else 1
		_cbc(
			line,
			quantity_tag,
			f"{flt(item.billed_quantity) * multiplier:g}",
			unitCode=item.unit_code or "C62",
		)
		_amount(line, "LineExtensionAmount", item.total_amount, self.currency)

		item_el = _cac(line, "Item")
		if self.profile > EInvoiceProfile.BASIC and item.product_description:
			_cbc(item_el, "Description", item.product_description)
		_cbc(item_el, "Name", item.product_name)
		if self.profile > EInvoiceProfile.BASIC and item.seller_product_id:
			sellers_id = _cac(item_el, "SellersItemIdentification")
			_cbc(sellers_id, "ID", item.seller_product_id)

		category_code = self._tax_category_code()
		# BR-AE-05, BR-E-05, BR-G-05, BR-IC-05, BR-Z-05: exempt-like categories carry 0%.
		rate = 0 if category_code in ("AE", "E", "G", "K", "Z") else (item.tax_rate or 0)
		classified = _cac(item_el, "ClassifiedTaxCategory")
		_cbc(classified, "ID", category_code)
		_cbc(classified, "Percent", f"{flt(rate, 2):g}")
		scheme = _cac(classified, "TaxScheme")
		_cbc(scheme, "ID", "VAT")

		price = _cac(line, "Price")
		_amount(price, "PriceAmount", flt(item.net_rate) * multiplier, self.currency)
