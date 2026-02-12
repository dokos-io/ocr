from typing import TYPE_CHECKING

import frappe
from frappe import _, _dict

from drafthorse.models.document import Document as DrafthorseDocument
from lxml.etree import XMLSyntaxError

from etransactions.schematron import get_validation_errors
from etransactions.utils import EInvoiceProfile, get_profile
from etransactions.utils.xml import get_xml_bytes

if TYPE_CHECKING:
	from drafthorse.models.accounting import ApplicableTradeTax, MonetarySummation
	from drafthorse.models.party import PostalTradeAddress, TradeParty
	from drafthorse.models.payment import PaymentTerms
	from drafthorse.models.trade import BillingSpecifiedPeriod, PaymentMeans
	from drafthorse.models.tradelines import LineItem

	from frappe.core.doctype.file.file import File
	from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice


class eInvoiceParser:
	def __init__(self, doc: eInvoice) -> None:
		self.einvoice_document = doc

	@classmethod
	def get_einvoice_document(cls, cls_xml_bytes):
		try:
			return DrafthorseDocument.parse(cls_xml_bytes, strict=False)
		except Exception:
			# Drafthorse tries to parse string fields (like ClassCode) as Decimal. TODO: Fix this issue
			try:
				from lxml import etree
				tree = etree.fromstring(cls_xml_bytes)

				# Remove elements known to cause issues in drafthorse.
				# DesignatedProductClassification/ClassCode
				for el in tree.xpath("//*[local-name()='DesignatedProductClassification']"):
					el.getparent().remove(el)

				return DrafthorseDocument.parse(etree.tostring(tree), strict=False)
			except Exception:
				frappe.throw(
					_("The uploaded file does not contain valid XML data or could not be parsed by the e-invoice engine."),
					XMLSyntaxError,
				)

	@classmethod
	def get_xml_bytes(cls, einvoice: File) -> bytes:
		return get_xml_bytes(einvoice)

	def parse_einvoice(self) -> None:
		einvoice: File = frappe.get_doc("File", self.einvoice_document.einvoice)
		xml_bytes = eInvoiceParser.get_xml_bytes(einvoice)
		self.einvoice_document.einvoice_xml = xml_bytes
		doc = eInvoiceParser.get_einvoice_document(xml_bytes)

		self.profile = get_profile(doc.context.guideline_parameter.id._text).value
		self.einvoice_document.profile = self.profile
		self._validate_schematron(xml_bytes)

		self.einvoice_document.id = str(doc.header.id)
		self.einvoice_document.issue_date = str(doc.header.issue_date_time)
		self.einvoice_document.currency = str(doc.trade.settlement.currency_code)

		self.parse_seller(doc.trade.agreement.seller)
		self.parse_buyer(doc.trade.agreement.buyer)

		self.einvoice_document.buyer_reference = doc.trade.agreement.buyer_order.issuer_assigned_id._text
		if (
			not self.einvoice_document.purchase_order
			and self.einvoice_document.buyer_reference
			and frappe.db.exists("Purchase Order", self.einvoice_document.buyer_reference)
		):
			self.einvoice_document.purchase_order = self.buyer_reference

		self.einvoice_document.items = []
		for li in doc.trade.items.children:
			self.parse_line_item(li)

		self.einvoice_document.taxes = []
		for tax in doc.trade.settlement.trade_tax.children:
			self.parse_tax(tax)

		self.einvoice_document.payment_terms = []
		for term in doc.trade.settlement.terms.children:
			self.parse_payment_term(term)

		self.parse_monetary_summation(doc.trade.settlement.monetary_summation)
		self.parse_bank_details(doc.trade.settlement.payment_means)
		self.parse_billing_period(doc.trade.settlement.period)


	def _validate_schematron(self, xml_bytes):
		self.einvoice_document.validation_errors = ""
		self.einvoice_document.validation_warnings = ""
		xml_string = xml_bytes.decode("utf-8")

		try:
			validation_errors, validation_warnings = get_validation_errors(
				xml_string, EInvoiceProfile(self.profile)
			)
		except Exception:
			frappe.log_error(
				title="E Invoice schematron validation",
				reference_doctype=self.einvoice_document.doctype,
				reference_name=self.einvoice_document.name,
			)
			frappe.msgprint(
				_("Could not validate E Invoice schematron. See Error Log for details."),
				alert=True,
				indicator="orange",
			)
			return

		if any(validation_errors):
			self.einvoice_document.e_invoice_is_correct = 0
			self.einvoice_document.validation_errors += "\n".join(validation_errors)
		else:
			self.einvoice_document.e_invoice_is_correct = 1

		if any(validation_warnings):
			self.einvoice_document.validation_warnings += "\n".join(validation_warnings)


	def parse_seller(self, seller: TradeParty):
		self.einvoice_document.seller_name = str(seller.name)
		self.einvoice_document.seller_tax_id = (
			seller.tax_registrations.children[0].id._text if seller.tax_registrations.children else None
		)
		self.einvoice_document.seller_electronic_address = str(seller.electronic_address.uri_ID._text)
		self.einvoice_document.seller_electronic_address_scheme = str(seller.electronic_address.uri_ID._scheme_id)
		self.parse_address(seller.address, "seller")

	def parse_buyer(self, buyer: TradeParty):
		self.einvoice_document.buyer_name = str(buyer.name)
		self.einvoice_document.buyer_electronic_address = str(buyer.electronic_address.uri_ID._text)
		self.einvoice_document.buyer_electronic_address_scheme = str(buyer.electronic_address.uri_ID._scheme_id)
		self.parse_address(buyer.address, "buyer")

	def parse_address(self, address: PostalTradeAddress, prefix: str) -> _dict:
		country = frappe.db.get_value("Country", {"code": str(address.country_id).lower()}, "name")

		self.einvoice_document.set(f"{prefix}_city", str(address.city_name))
		self.einvoice_document.set(f"{prefix}_address_line_1", str(address.line_one))
		self.einvoice_document.set(f"{prefix}_address_line_2", str(address.line_two))
		self.einvoice_document.set(f"{prefix}_postcode", str(address.postcode))
		self.einvoice_document.set(f"{prefix}_country", str(country))

	def parse_line_item(self, li: LineItem):
		item = self.einvoice_document.append("items")

		net_rate = float(li.agreement.net.amount._value)
		basis_qty = float(li.agreement.net.basis_quantity._amount or "1")
		rate = net_rate / basis_qty

		product_name_full = str(li.product.name)
		product_description = str(li.product.description)
		if len(product_name_full) > 140:
			item.product_name = product_name_full[:140]
			item.product_description = product_name_full + " | " + product_description
		else:
			item.product_name = product_name_full
			item.product_description = product_description
		item.seller_product_id = str(li.product.seller_assigned_id)
		item_code = str(li.product.buyer_assigned_id)
		if item_code and not frappe.db.exists("Item", item_code):
			item_code = None

		item.item = item_code or None
		item.billed_quantity = flt_or_none(li.delivery.billed_quantity._amount)
		item.unit_code = str(li.delivery.billed_quantity._unit_code)
		item.net_rate = rate
		item.tax_rate = flt_or_none(li.settlement.trade_tax.rate_applicable_percent._value)
		item.total_amount = flt_or_none(li.settlement.monetary_summation.total_amount._value)

	def parse_tax(self, tax: ApplicableTradeTax):
		t = self.einvoice_document.append("taxes")
		t.basis_amount = flt_or_none(tax.basis_amount._value)
		t.rate_applicable_percent = flt_or_none(tax.rate_applicable_percent._value)
		t.calculated_amount = flt_or_none(tax.calculated_amount._value)

	def parse_payment_term(self, term: PaymentTerms):
		if not term.partial_amount.children:
			self.einvoice_document.due_date = term.due._value
			return

		t = self.einvoice_document.append("payment_terms")
		t.due = term.due._value
		partial_amount = None
		for row in term.partial_amount.children:
			if isinstance(row, tuple):
				# row = (amount, currency)
				if row[1] == self.einvoice_document.currency:
					partial_amount = row[0]
					break
			else:
				# row = amount
				partial_amount = row
				break

		t.partial_amount = float(partial_amount) if partial_amount is not None else None
		t.description = term.description
		t.discount_basis_date = term.discount_terms.basis_date_time._value

		if term.discount_terms.calculation_percent._value:
			t.discount_calculation_percent = float(term.discount_terms.calculation_percent._value)

		if term.discount_terms.actual_amount._value:
			t.discount_actual_amount = float(term.discount_terms.actual_amount._value)

	def parse_monetary_summation(self, summation: MonetarySummation):
		self.einvoice_document.line_total = flt_or_none(summation.line_total._value)
		self.einvoice_document.allowance_total = flt_or_none(summation.allowance_total._value)
		self.einvoice_document.charge_total = flt_or_none(summation.charge_total._value)
		self.einvoice_document.tax_basis_total = flt_or_none(summation.tax_basis_total._amount)
		for value, currency in summation.tax_total_other_currency.children:
			if currency is None or currency == self.einvoice_document.currency:
				self.einvoice_document.tax_total = flt_or_none(value)
				break
		self.einvoice_document.grand_total = flt_or_none(summation.grand_total._amount)
		self.einvoice_document.total_prepaid = flt_or_none(summation.prepaid_total._value)
		self.einvoice_document.due_payable = flt_or_none(summation.due_amount._value)

	def parse_bank_details(self, payment_means: PaymentMeans):
		self.einvoice_document.payee_iban = payment_means.payee_account.iban._text or None

		if EInvoiceProfile(self.einvoice_document.profile) >= EInvoiceProfile.EN16931:
			self.einvoice_document.payee_account_name = payment_means.payee_account.account_name._text or None
			self.einvoice_document.payee_bic = payment_means.payee_institution.bic._text or None

	def parse_billing_period(self, period: BillingSpecifiedPeriod):
		self.einvoice_document.billing_period_start = period.start._value
		self.einvoice_document.billing_period_end = period.end._value


def flt_or_none(value) -> float | None:
	return float(value) if value is not None else None