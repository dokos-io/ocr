import mimetypes
import os
from typing import TYPE_CHECKING

from drafthorse.models.accounting import ApplicableTradeTax, AppliedTradeTax
from drafthorse.models.document import Document, IncludedNote
from drafthorse.models.party import TaxRegistration
from drafthorse.models.payment import PaymentTerms
from drafthorse.models.references import AdditionalReferencedDocument
from drafthorse.models.trade import LogisticsServiceCharge
from drafthorse.models.tradelines import LineItem

import frappe
from frappe import _
from frappe.core.doctype.file.utils import find_file_by_url
from frappe.core.utils import html2text
from frappe.utils.data import date_diff, flt, getdate, to_markdown

from etransactions.common_codes import CommonCodeRetriever
from etransactions.utils import EInvoiceProfile, get_guideline, as_base_64
from etransactions.utils.vat import validate_vat_id


if TYPE_CHECKING:
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
	from erpnext.accounts.doctype.sales_invoice_item.sales_invoice_item import SalesInvoiceItem
	from erpnext.selling.doctype.customer.customer import Customer
	from erpnext.setup.doctype.company.company import Company
	from frappe.contacts.doctype.address.address import Address
	from frappe.contacts.doctype.contact.contact import Contact
	from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice


uom_codes = CommonCodeRetriever(
	["urn:xoev-de:kosit:codeliste:rec20_3", "urn:xoev-de:kosit:codeliste:rec21_3"], "C62"
)
payment_means_codes = CommonCodeRetriever(["urn:xoev-de:xrechnung:codeliste:untdid.4461_3"], "ZZZ")
duty_tax_fee_category_codes = CommonCodeRetriever(["urn:xoev-de:kosit:codeliste:untdid.5305_3"], "S")
vat_exemption_reason_codes = CommonCodeRetriever(["urn:xoev-de:kosit:codeliste:vatex_1"], "vatex-eu-ae")


class EInvoiceMapper:
	def __init__(self, einvoice: eInvoice):
		self.einvoice = einvoice
		if not self.einvoice.sales_invoice:
			frappe.throw(_("This document must be linked to sales invoice in order to generate an eInvoice"))

		self.sales_invoice: SalesInvoice = frappe.get_doc("Sales Invoice", self.einvoice.sales_invoice)

		self.seller_address = None
		self.buyer_address = None
		self.shipping_address = None
		self.seller_contact = None
		self.buyer_contact = None
		self.customer = None
		self.company = None

	def run(self):
		self.check_permissions()

		self.map_seller_address()
		self.map_buyer_address()
		self.map_shipping_address()
		self.map_seller_contact()
		self.map_buyer_contact()

		self.customer = frappe.get_doc("Customer", self.sales_invoice.customer)
		self.company = frappe.get_doc("Company", self.sales_invoice.company)

	def check_permissions(self):
		self.sales_invoice.check_permission("read")

	def map_seller_address(self):
		seller_address_map = {
			"address_line1": "seller_address_line_1",
			"address_line2": "seller_address_line_2",
			"pincode": "seller_postcode",
			"city": "seller_city",
			"country": "seller_country",
		}

		if self.sales_invoice.company_address:
			self.seller_address = frappe.get_doc("Address", self.sales_invoice.company_address)

		if not self.seller_address:
			return

		for address_field, einvoice_field in seller_address_map.items():
			self.einvoice.set(einvoice_field, self.buyer_address.get(address_field))

	def map_buyer_address(self):
		buyer_address_map = {
			"address_line1": "buyer_address_line_1",
			"address_line2": "buyer_address_line_2",
			"pincode": "buyer_postcode",
			"city": "buyer_city",
			"country": "buyer_country",
		}

		if self.sales_invoice.customer_address:
			self.buyer_address = frappe.get_doc("Address", self.sales_invoice.customer_address)

		if not self.buyer_address:
			return

		for address_field, einvoice_field in buyer_address_map.items():
			self.einvoice.set(einvoice_field, self.buyer_address.get(address_field))

	def map_shipping_address(self):
		if self.sales_invoice.shipping_address_name:
			self.shipping_address = frappe.get_doc("Address", self.sales_invoice.shipping_address_name)


	def map_seller_contact(self):
		if self.sales_invoice.company_contact_person:
			self.seller_contact = frappe.get_doc("Contact", self.sales_invoice.company_contact_person)


	def map_buyer_contact(self):
		if self.sales_invoice.company_contact_person:
			self.buyer_contact = frappe.get_doc("Contact", self.sales_invoice.contact_person)


class EInvoiceGenerator:
	"""Map ERPNext entities to a Drafthorse document."""

	def __init__(
		self,
		profile: EInvoiceProfile,
		invoice: SalesInvoice,
		company: Company,
		customer: Customer,
		seller_address: Address | None = None,
		buyer_address: Address | None = None,
		shipping_address: Address | None = None,
		seller_contact: Contact | None = None,
		buyer_contact: Contact | None = None,
	):
		self.profile = profile
		self.invoice = invoice
		self.company = company
		self.customer = customer
		self.seller_address = seller_address
		self.buyer_address = buyer_address
		self.shipping_address = shipping_address
		self.seller_contact = seller_contact
		self.buyer_contact = buyer_contact
		self.doc = None
		self.item_tax_rates = set()
		self.delivery_dates = []

	def get_einvoice(self) -> Document | None:
		"""Return the einvoice document as a Python object."""
		return self.doc

	def create_einvoice(self):
		"""Create the einvoice document as a Python object."""
		self.doc = Document()

		self._set_context()
		self._set_header()
		self._set_seller()
		self._set_buyer()

		if self.invoice.etransactions_buyer_reference:
			self.doc.trade.agreement.buyer_reference = self.invoice.etransactions_buyer_reference

		if self.invoice.po_no:
			self.doc.trade.agreement.buyer_order.issuer_assigned_id = self.invoice.po_no

			if self.invoice.po_date and self.profile >= EInvoiceProfile.EXTENDED:
				self.doc.trade.agreement.buyer_order.issue_date_time = getdate(self.invoice.po_date)

		# if self.profile >= EInvoiceProfile.EN16931: # TODO: No yet implemented
		# 	self._embed_attachment()

		sales_orders = set()
		for item in self.invoice.items:
			if item.sales_order:
				sales_orders.add(item.sales_order)

			self._add_line_item(item)

		if len(sales_orders) == 1 and self.profile >= EInvoiceProfile.EXTENDED:
			so_name = sales_orders.pop()
			self.doc.trade.agreement.seller_order.issuer_assigned_id = so_name
			self.doc.trade.agreement.seller_order.issue_date_time = frappe.db.get_value(
				"Sales Order", so_name, "transaction_date"
			)

		tax_added = self._add_taxes_and_charges()
		if not tax_added:
			self._add_empty_tax()

		self.doc.trade.settlement.currency_code = self.invoice.currency
		self._add_payment_means()

		if self.invoice.from_date:
			self.doc.trade.settlement.period.start = getdate(self.invoice.from_date)

		if self.invoice.to_date:
			self.doc.trade.settlement.period.end = getdate(self.invoice.to_date)

		self._add_delivery_date()
		self._add_payment_terms()
		self._set_totals()

	def _embed_attachment(self):
		"""Add the embedded document to the einvoice."""
		if not self.invoice.einvoice_embedded_document:
			return

		file = find_file_by_url(self.invoice.einvoice_embedded_document)

		content = None
		if not file.is_remote_file:
			file_name = os.path.basename(file.file_url)
			mime_type = mimetypes.guess_type(file.file_url)[0]
			content = as_base_64(file.get_content())

		ref_doc = AdditionalReferencedDocument()
		ref_doc.issuer_assigned_id = file.name
		if file.is_remote_file:
			ref_doc.uri_id = file.file_url
		else:
			ref_doc.attached_object = (mime_type, file_name, content)
		ref_doc.type_code = "916"  # "Related document" according to UNTDID 1001
		self.doc.trade.agreement.additional_references.add(ref_doc)

	def _set_context(self):
		"""Set default context according to XRechnung 3.0.2"""
		self.doc.context.business_parameter.id = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
		self.doc.context.guideline_parameter.id = get_guideline(self.profile)

	def _set_header(self):
		self.doc.header.id = self.invoice.name

		# https://unece.org/fileadmin/DAM/trade/untdid/d16b/tred/tred1001.htm
		if self.invoice.is_return:
			# -- Credit note --
			# Document/message for providing credit information to the relevant party.
			self.doc.header.type_code = "381"
			self.doc.trade.settlement.invoice_referenced_document.issuer_assigned_id = (
				self.invoice.return_against
			)
			self.doc.trade.settlement.invoice_referenced_document.issue_date_time = frappe.db.get_value(
				"Sales Invoice", self.invoice.return_against, "posting_date"
			)
		elif self.invoice.amended_from:
			# -- Corrected invoice --
			# Commercial invoice that includes revised information differing from an
			# earlier submission of the same invoice.
			self.doc.header.type_code = "384"
			self.doc.trade.settlement.invoice_referenced_document.issuer_assigned_id = (
				self.invoice.amended_from
			)
			self.doc.trade.settlement.invoice_referenced_document.issue_date_time = frappe.db.get_value(
				"Sales Invoice", self.invoice.amended_from, "posting_date"
			)
		else:
			# -- Commercial invoice --
			# Document/message claiming payment for goods or services supplied under
			# conditions agreed between seller and buyer.
			self.doc.header.type_code = "380"

		self.doc.header.issue_date_time = getdate(self.invoice.posting_date)

		if self.invoice.terms:
			note = IncludedNote(subject_code="ABC")  # Conditions of sale or purchase
			note.content.add(to_markdown(self.invoice.terms).strip())
			self.doc.header.notes.add(note)

		if self.invoice.incoterm:
			note = IncludedNote(subject_code="AAR")  # Terms of delivery
			note.content.add(f"{self.invoice.incoterm} {self.invoice.named_place or ''}".strip())
			self.doc.header.notes.add(note)

	def _set_seller(self):
		self.doc.trade.agreement.seller.name = self.invoice.company
		self._set_seller_tax_id()

		if self.profile > EInvoiceProfile.BASIC:
			self._set_seller_contact()

		self._set_seller_id()
		self._set_seller_electronic_address()
		self._set_seller_address()

	def _set_seller_id(self):
		for row in self.customer.supplier_numbers:
			if row.company == self.invoice.company and row.supplier_number:
				self.doc.trade.agreement.seller.id = row.supplier_number
				break

	def _set_seller_tax_id(self):
		if not self.invoice.company_tax_id:
			return

		try:
			seller_tax_id = validate_vat_id(self.invoice.company_tax_id.strip())
			seller_vat_scheme = "VA"
		except ValueError:
			seller_tax_id = self.invoice.company_tax_id.strip()
			seller_vat_scheme = "FC"

		self.doc.trade.agreement.seller.tax_registrations.add(
			TaxRegistration(
				id=(seller_vat_scheme, seller_tax_id),
			)
		)

	def _set_seller_address(self):
		if not self.seller_address:
			return

		self.doc.trade.agreement.seller.address.line_one = self.seller_address.address_line1
		self.doc.trade.agreement.seller.address.line_two = self.seller_address.address_line2
		self.doc.trade.agreement.seller.address.postcode = self.seller_address.pincode
		self.doc.trade.agreement.seller.address.city_name = self.seller_address.city
		self.doc.trade.agreement.seller.address.country_id = frappe.db.get_value(
			"Country", self.seller_address.country, "code"
		).upper()

	def _set_seller_electronic_address(self):
		if self.company.etransactions_electronic_address_scheme and self.company.etransactions_electronic_address:
			self.doc.trade.agreement.seller.electronic_address.uri_ID = (
				frappe.db.get_value("Common Code", self.company.etransactions_electronic_address_scheme, "common_code"),
				self.company.etransactions_electronic_address,
			)
			return

		if self.seller_contact and self.seller_contact.email_id:
			electronic_address = self.seller_contact.email_id
		else:
			electronic_address = self.company.email

		if electronic_address:
			self.doc.trade.agreement.seller.electronic_address.uri_ID = ("EM", electronic_address)

	def _set_seller_contact(self):
		seller_contact_phone = self.company.phone_no
		if self.seller_contact:
			self.doc.trade.agreement.seller.contact.person_name = self.seller_contact.full_name
			if self.seller_contact.department:
				self.doc.trade.agreement.seller.contact.department_name = self.seller_contact.department
			if self.seller_contact.email_id:
				self.doc.trade.agreement.seller.contact.email.address = self.seller_contact.email_id
			if self.seller_contact.phone:
				seller_contact_phone = self.seller_contact.phone

		if seller_contact_phone and self.profile >= EInvoiceProfile.EN16931:
			self.doc.trade.agreement.seller.contact.telephone.number = seller_contact_phone

		if self.company.fax and self.profile >= EInvoiceProfile.EXTENDED:
			self.doc.trade.agreement.seller.contact.fax.number = self.company.fax

	def _set_buyer(self):
		if frappe.db.get_single_value("Selling Settings", "cust_master_name") != "Customer Name":
			self.doc.trade.agreement.buyer.id = self.invoice.customer

		self.doc.trade.agreement.buyer.name = self.invoice.customer_name

		self._set_buyer_address()
		self._set_shipping_address()

		if self.profile > EInvoiceProfile.BASIC:
			self._set_buyer_contact()

		self._set_buyer_electronic_address()
		self._set_buyer_tax_id()

	def _set_buyer_electronic_address(self):
		if self.customer.etransactions_electronic_address_scheme and self.customer.etransactions_electronic_address:
			self.doc.trade.agreement.buyer.electronic_address.uri_ID = (
				frappe.db.get_value("Common Code", self.customer.etransactions_electronic_address_scheme, "common_code"),
				self.customer.etransactions_electronic_address,
			)
			return

		if self.invoice.contact_email:
			self.doc.trade.agreement.buyer.electronic_address.uri_ID = ("EM", self.invoice.contact_email)
		elif self.buyer_address and self.buyer_address.email_id:
			self.doc.trade.agreement.buyer.electronic_address.uri_ID = ("EM", self.buyer_address.email_id)

	def _set_buyer_tax_id(self):
		if not self.invoice.tax_id:
			return

		try:
			customer_tax_id = validate_vat_id(self.invoice.tax_id.strip())
			customer_vat_scheme = "VA"
		except ValueError:
			customer_tax_id = self.invoice.tax_id.strip()
			customer_vat_scheme = "FC"

		self.doc.trade.agreement.buyer.tax_registrations.add(
			TaxRegistration(
				id=(customer_vat_scheme, customer_tax_id),
			)
		)

	def _set_buyer_address(self):
		if not self.buyer_address:
			return

		self.doc.trade.agreement.buyer.address.line_one = self.buyer_address.address_line1
		self.doc.trade.agreement.buyer.address.line_two = self.buyer_address.address_line2
		self.doc.trade.agreement.buyer.address.postcode = self.buyer_address.pincode
		self.doc.trade.agreement.buyer.address.city_name = self.buyer_address.city
		self.doc.trade.agreement.buyer.address.country_id = frappe.db.get_value(
			"Country", self.buyer_address.country, "code"
		).upper()

	def _set_shipping_address(self):
		if not self.shipping_address:
			return

		self.doc.trade.delivery.ship_to.name = (
			self.shipping_address.address_title or self.invoice.customer_name
		)
		self.doc.trade.delivery.ship_to.address.line_one = self.shipping_address.address_line1
		self.doc.trade.delivery.ship_to.address.line_two = self.shipping_address.address_line2
		self.doc.trade.delivery.ship_to.address.postcode = self.shipping_address.pincode
		self.doc.trade.delivery.ship_to.address.city_name = self.shipping_address.city
		self.doc.trade.delivery.ship_to.address.country_id = frappe.db.get_value(
			"Country", self.shipping_address.country, "code"
		).upper()

	def _set_buyer_contact(self):
		if self.buyer_contact:
			self.doc.trade.agreement.buyer.contact.person_name = self.buyer_contact.full_name
			if self.buyer_contact.department:
				self.doc.trade.agreement.buyer.contact.department_name = self.buyer_contact.department
			if self.buyer_contact.email_id:
				self.doc.trade.agreement.buyer.contact.email.address = self.buyer_contact.email_id

			if self.profile >= EInvoiceProfile.EN16931:
				if self.buyer_contact.phone:
					self.doc.trade.agreement.buyer.contact.telephone.number = self.buyer_contact.phone
				elif self.buyer_contact.mobile_no:
					self.doc.trade.agreement.buyer.contact.telephone.number = self.buyer_contact.mobile_no

	def _add_line_item(self, item: SalesInvoiceItem):
		li = LineItem()
		li.document.line_id = str(item.idx)
		li.product.name = item.item_name

		if self.profile > EInvoiceProfile.BASIC:
			li.product.seller_assigned_id = item.item_code
			li.product.buyer_assigned_id = item.customer_item_code
			li.product.description = html2text(item.description)

		# ERPNext won’t accept negative quantities, and the e-invoice rules (BR-27)
		# won’t accept negative prices. To work around this, we flip the signs:
		# a line that would have had a negative price and positive quantity is
		# instead sent with a positive price and a negative quantity.
		multiplier = -1 if item.net_rate < 0 and item.qty > 0 else 1

		li.agreement.net.amount = flt(item.net_rate, item.precision("net_rate")) * multiplier
		li.delivery.billed_quantity = (
			flt(item.qty, item.precision("qty")) * multiplier,
			uom_codes.get([("UOM", item.uom)]),
		)

		if item.delivery_note:
			posting_date = frappe.db.get_value("Delivery Note", item.delivery_note, "posting_date")
			self.delivery_dates.append(posting_date)

			if self.profile >= EInvoiceProfile.EXTENDED:
				li.delivery.delivery_note.issuer_assigned_id = item.delivery_note
				li.delivery.delivery_note.issue_date_time = getdate(posting_date)

		li.settlement.trade_tax.type_code = "VAT"
		li.settlement.trade_tax.category_code = duty_tax_fee_category_codes.get(
			[
				("Item Tax Template", item.item_tax_template),
				("Account", item.income_account),
				("Tax Category", self.invoice.tax_category),
				("Sales Taxes and Charges Template", self.invoice.taxes_and_charges),
			]
		)
		if li.settlement.trade_tax.category_code._text in ("AE", "E", "G", "K", "Z"):
			# BR-AE-05, BR-E-05, BR-G-05, BR-IC-05, BR-Z-05
			li.settlement.trade_tax.rate_applicable_percent = 0
		else:
			item_tax_rate = get_item_rate(item.item_tax_template, self.invoice.taxes)
			self.item_tax_rates.add(item_tax_rate)
			li.settlement.trade_tax.rate_applicable_percent = item_tax_rate

		if li.settlement.trade_tax.rate_applicable_percent._value == 0:
			li.settlement.trade_tax.exemption_reason_code = vat_exemption_reason_codes.get(
				[
					("Item Tax Template", item.item_tax_template),
					("Account", item.income_account),
					("Tax Category", self.invoice.tax_category),
					("Sales Taxes and Charges Template", self.invoice.taxes_and_charges),
				]
			).upper()

		li.settlement.monetary_summation.total_amount = flt(item.net_amount, item.precision("net_amount"))
		self.doc.trade.items.add(li)

	def _add_taxes_and_charges(self):
		tax_added = False
		for i, tax in enumerate(self.invoice.taxes):
			if tax.charge_type == "Actual" and self.profile >= EInvoiceProfile.EXTENDED:
				service_charge = LogisticsServiceCharge()
				service_charge.description = tax.description
				service_charge.applied_amount = tax.tax_amount

				if len(self.invoice.taxes) > i + 1:
					vat_line = self.invoice.taxes[i + 1]
					if vat_line.charge_type in ("On Previous Row Amount", "On Previous Row Total"):
						# Add applied VAT for the service charge (BR-FXEXT-S-08)
						service_charge_tax = AppliedTradeTax()
						service_charge_tax.type_code = "VAT"
						service_charge_tax.rate_applicable_percent = vat_line.rate
						service_charge_tax.category_code = duty_tax_fee_category_codes.get(
							[
								("Account", vat_line.account_head),
								("Tax Category", self.invoice.tax_category),
								("Sales Taxes and Charges Template", self.invoice.taxes_and_charges),
							]
						)
						service_charge.trade_tax.add(service_charge_tax)

				self.doc.trade.settlement.service_charge.add(service_charge)
			elif tax.charge_type == "On Net Total":
				trade_tax = ApplicableTradeTax()
				trade_tax.calculated_amount = tax.tax_amount
				trade_tax.type_code = "VAT"
				trade_tax.category_code = duty_tax_fee_category_codes.get(
					[
						("Account", tax.account_head),
						("Tax Category", self.invoice.tax_category),
						("Sales Taxes and Charges Template", self.invoice.taxes_and_charges),
					]
				)
				tax_rate = tax.rate or frappe.db.get_value("Account", tax.account_head, "tax_rate") or 0
				trade_tax.rate_applicable_percent = tax_rate

				if len(self.invoice.taxes) == 1:
					# We only have one tax, so we can use the net total as basis amount
					trade_tax.basis_amount = self.invoice.net_total
					if len(self.item_tax_rates) == 1 and tax_rate == 0:
						# We only have one tax rate on the line items, but it was not specified on the tax row
						# so we use the tax rate from the line items.
						trade_tax.rate_applicable_percent = self.item_tax_rates.pop()
				elif hasattr(tax, "net_amount"):
					trade_tax.basis_amount = tax.net_amount
				elif hasattr(tax, "custom_net_amount"):
					trade_tax.basis_amount = tax.custom_net_amount
				elif tax.tax_amount and tax_rate:
					# We don't know the basis amount for this tax, so we try to calculate it
					trade_tax.basis_amount = round(tax.tax_amount / tax_rate * 100, 2)
				else:
					trade_tax.basis_amount = 0

				self.doc.trade.settlement.trade_tax.add(trade_tax)
				tax_added = True
			elif tax.charge_type == "On Previous Row Amount":
				trade_tax = ApplicableTradeTax()
				trade_tax.basis_amount = self.invoice.taxes[i - 1].tax_amount
				trade_tax.rate_applicable_percent = tax.rate
				trade_tax.calculated_amount = tax.tax_amount

				if self.invoice.taxes[i - 1].charge_type == "Actual":
					# VAT for a LogisticsServiceCharge
					trade_tax.type_code = "VAT"
				else:
					# A tax or duty applied on and in addition to existing duties and taxes.
					trade_tax.type_code = "SUR"

				trade_tax.category_code = duty_tax_fee_category_codes.get(
					[
						("Account", tax.account_head),
						("Tax Category", self.invoice.tax_category),
						("Sales Taxes and Charges Template", self.invoice.taxes_and_charges),
					]
				)
				self.doc.trade.settlement.trade_tax.add(trade_tax)
				tax_added = True
			elif tax.charge_type == "On Previous Row Total":
				trade_tax = ApplicableTradeTax()
				trade_tax.basis_amount = self.invoice.taxes[i - 1].total
				trade_tax.rate_applicable_percent = tax.rate
				trade_tax.calculated_amount = tax.tax_amount

				if self.invoice.taxes[i - 1].charge_type == "Actual":
					# VAT for a LogisticsServiceCharge
					trade_tax.type_code = "VAT"
				else:
					# A tax or duty applied on and in addition to existing duties and taxes.
					trade_tax.type_code = "SUR"

				trade_tax.category_code = duty_tax_fee_category_codes.get(
					[
						("Account", tax.account_head),
						("Tax Category", self.invoice.tax_category),
						("Sales Taxes and Charges Template", self.invoice.taxes_and_charges),
					]
				)
				self.doc.trade.settlement.trade_tax.add(trade_tax)
				tax_added = True

		return tax_added

	def _add_empty_tax(self):
		"""Add a 0% tax to the document, since it is mandatory."""
		trade_tax = ApplicableTradeTax()
		trade_tax.type_code = "VAT"  # [CII-DT-037] - TypeCode shall be 'VAT'
		trade_tax.category_code = duty_tax_fee_category_codes.get(
			[
				("Tax Category", self.invoice.tax_category),
				("Sales Taxes and Charges Template", self.invoice.taxes_and_charges),
			]
		)
		trade_tax.basis_amount = self.invoice.net_total
		trade_tax.rate_applicable_percent = 0
		trade_tax.calculated_amount = 0
		trade_tax.exemption_reason_code = vat_exemption_reason_codes.get(
			[
				("Tax Category", self.invoice.tax_category),
				("Sales Taxes and Charges Template", self.invoice.taxes_and_charges),
			]
		).upper()
		self.doc.trade.settlement.trade_tax.add(trade_tax)

	def _add_delivery_date(self):
		if self.delivery_dates:
			delivery_date = sorted(self.delivery_dates)[-1]
		elif self.invoice.to_date:
			delivery_date = self.invoice.to_date
		else:
			delivery_date = self.invoice.posting_date

		self.doc.trade.delivery.event.occurrence = getdate(delivery_date)

	def _add_payment_terms(self):
		for ps in self.invoice.payment_schedule:
			payment_terms = PaymentTerms()
			ps_description = ps.description or ""
			if ps.due_date:
				payment_terms.due = getdate(ps.due_date)

			if len(self.invoice.payment_schedule) > 1:
				payment_terms.partial_amount.add(
					(ps.payment_amount, None)
				)  # [CII-DT-031] - currencyID should not be present

			if ps.discount and ps.discount_date:
				if self.profile == EInvoiceProfile.EXTENDED:
					payment_terms.discount_terms.basis_date_time = getdate(ps.discount_date)
					payment_terms.discount_terms.basis_amount = ps.payment_amount
					if ps.discount_type == "Percentage":
						payment_terms.discount_terms.calculation_percent = ps.discount
					elif ps.discount_type == "Amount":
						payment_terms.discount_terms.actual_amount = ps.discount
				elif self.profile == EInvoiceProfile.XRECHNUNG:
					ps_description = ps_description.replace(
						"#", "//"
					)  # the character "#" is not allowed in the free text
					if ps.discount_type == "Percentage":
						discount_days = date_diff(ps.discount_date, self.invoice.posting_date)
						if discount_days < 0:
							basis_amount = (
								ps.payment_amount
								if round(ps.payment_amount, 2) != round(self.invoice.outstanding_amount, 2)
								else None
							)
							if ps_description:
								ps_description += "\n"
							ps_description += get_skonto_line(discount_days, ps.discount, basis_amount)
							ps_description += "\n"

			if ps_description:
				payment_terms.description = ps_description

			self.doc.trade.settlement.terms.add(payment_terms)

	def _add_payment_means(self):
		self.doc.trade.settlement.payment_means.type_code = payment_means_codes.get(
			[("Payment Terms Template", self.invoice.payment_terms_template)]
			+ [("Mode of Payment", term.mode_of_payment) for term in self.invoice.payment_schedule]
		)

		modes_of_payment = {ps.mode_of_payment for ps in self.invoice.payment_schedule if ps.mode_of_payment}
		for mode_of_payment in modes_of_payment:
			iban, bic = get_bank_details(mode_of_payment, self.invoice.company)
			if not iban:
				continue

			self.doc.trade.settlement.payment_means.payee_account.iban = iban

			if self.profile >= EInvoiceProfile.EN16931:
				self.doc.trade.settlement.payment_means.payee_account.account_name = self.invoice.company
				self.doc.trade.settlement.payment_means.payee_institution.bic = bic

			break

	def _set_totals(self):
		# [BR-DEC-09]-The allowed maximum number of decimals for the Sum of Invoice line net amount (BT-106) is 2.
		self.doc.trade.settlement.monetary_summation.line_total = flt(self.invoice.net_total, 2)

		actual_charge_total = sum(tax.tax_amount for tax in self.invoice.taxes if tax.charge_type == "Actual")
		if actual_charge_total:
			# [BR-DEC-11]-The allowed maximum number of decimals for the Sum of charges on document level (BT-108) is 2.
			self.doc.trade.settlement.monetary_summation.charge_total = flt(actual_charge_total, 2)

		# [BR-DEC-12]-The allowed maximum number of decimals for the Invoice total amount without VAT (BT-109) is 2.
		self.doc.trade.settlement.monetary_summation.tax_basis_total = flt(
			self.invoice.net_total + actual_charge_total, 2
		)

		tax_total = sum(tax.tax_amount for tax in self.invoice.taxes if tax.charge_type != "Actual")
		# [BR-DEC-13]-The allowed maximum number of decimals for the Invoice total VAT amount (BT-110) is 2.
		self.doc.trade.settlement.monetary_summation.tax_total_other_currency.add(
			(flt(tax_total, 2), self.invoice.currency)
		)

		# [BR-DEC-14]-The allowed maximum number of decimals for the Invoice total amount with VAT (BT-112) is 2.
		self.doc.trade.settlement.monetary_summation.grand_total = flt(self.invoice.grand_total, 2)

		# [BR-DEC-16]-The allowed maximum number of decimals for the Paid amount (BT-113) is 2.
		if self.invoice.outstanding_amount == 0:
			self.doc.trade.settlement.monetary_summation.prepaid_total = flt(self.invoice.grand_total, 2)
		else:
			self.doc.trade.settlement.monetary_summation.prepaid_total = flt(self.invoice.total_advance, 2)

		# [BR-DEC-18]-The allowed maximum number of decimals for the Amount due for payment (BT-115) is 2.
		self.doc.trade.settlement.monetary_summation.due_amount = flt(self.invoice.outstanding_amount, 2)


def get_item_rate(item_tax_template: str | None, taxes: list[dict]) -> float | None:
	"""Get the tax rate for an item from the item tax template and the taxes table."""
	if item_tax_template:
		# match the accounts from the taxes table with the rate from the item tax template
		tax_template = frappe.get_doc("Item Tax Template", item_tax_template)
		applicable_accounts = [tax.account_head for tax in taxes if tax.account_head]

		for item_tax in tax_template.taxes:
			if item_tax.tax_type in applicable_accounts:
				return item_tax.tax_rate

	# if only one tax is on net total, return its rate
	tax_rates = [invoice_tax.rate for invoice_tax in taxes if invoice_tax.charge_type == "On Net Total"]
	return tax_rates[0] if len(tax_rates) == 1 else None


def get_bank_details(mode_of_payment: str, company: str) -> tuple[str | None, str | None]:
	"""Get the bank details for a mode of payment."""
	empty_tuple = (None, None)
	if frappe.db.get_value("Mode of Payment", mode_of_payment, "type") != "Bank":
		return empty_tuple

	account = frappe.db.get_value(
		"Mode of Payment Account", {"parent": mode_of_payment, "company": company}, "default_account"
	)
	if not account:
		return empty_tuple

	bank_account_name = frappe.db.get_value(
		"Bank Account", {"account": account, "company": company, "is_company_account": 1, "disabled": 0}
	)
	if not bank_account_name:
		return empty_tuple

	iban, bank = frappe.db.get_value("Bank Account", bank_account_name, ["iban", "bank"])
	if not iban:
		return empty_tuple

	bic = frappe.db.get_value("Bank", bank, "swift_number") if bank else None
	return (iban, bic or None)


def get_skonto_line(days: int, percent: float, basis_amount: float | None = None):
	"""Return a string containing codified early payment discount terms. Specific to Germany

	According to the document [Angabe von Skonto bei der Nutzung des Übertragungskanals
	„Upload“ an den Rechnungseingangsplattformen des Bundes](https://www.e-rechnung-bund.de/wp-content/uploads/2023/04/Angabe-Skonto-Upload.pdf)
	"""
	parts = [
		"SKONTO",
		f"TAGE={days}",
		f"PROZENT={percent:.2f}",
	]

	if basis_amount:
		parts.append(f"BASISBETRAG={basis_amount:.2f}")

	return "#" + "#".join(parts) + "#"