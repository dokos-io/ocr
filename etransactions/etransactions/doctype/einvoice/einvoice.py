# Copyright (c) 2026, ALYF GmbH, Dokos SAS and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING

import frappe
from erpnext import get_default_company
from erpnext.edi.doctype.code_list.code_list import get_docnames_for

from frappe import _
from frappe.model.document import Document

from etransactions.controllers.entity_resolver import InvoiceEntityResolverMixin
from etransactions.etransactions.doctype.einvoice.parser import eInvoiceParser
from etransactions.etransactions.doctype.einvoice.generator import EInvoiceMapper, EInvoiceGenerator
from etransactions.schematron import get_validation_errors
from etransactions.utils import EInvoiceProfile, get_drafthorse_schema


if TYPE_CHECKING:
	from erpnext.stock.doctype.item.item import Item
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice


class eInvoice(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from etransactions.etransactions.doctype.einvoice_item.einvoice_item import eInvoiceItem
		from etransactions.etransactions.doctype.einvoice_payment_term.einvoice_payment_term import eInvoicePaymentTerm
		from etransactions.etransactions.doctype.einvoice_trade_tax.einvoice_trade_tax import eInvoiceTradeTax
		from frappe.types import DF

		allowance_total: DF.Currency
		amended_from: DF.Link | None
		billing_period_end: DF.Date | None
		billing_period_start: DF.Date | None
		buyer_address_line_1: DF.Data | None
		buyer_address_line_2: DF.Data | None
		buyer_city: DF.Data | None
		buyer_country: DF.Link | None
		buyer_electronic_address: DF.Data | None
		buyer_electronic_address_scheme: DF.Data | None
		buyer_name: DF.Data | None
		buyer_postcode: DF.Data | None
		buyer_reference: DF.Data | None
		charge_total: DF.Currency
		company: DF.Link | None
		currency: DF.Link | None
		due_date: DF.Date | None
		due_payable: DF.Currency
		e_invoice_is_correct: DF.Check
		einvoice: DF.Link | None
		einvoice_type: DF.Literal["Incoming", "Outgoing"]
		einvoice_xml: DF.HTMLEditor | None
		grand_total: DF.Currency
		id: DF.Data | None
		issue_date: DF.Date | None
		items: DF.Table[eInvoiceItem]
		line_total: DF.Currency
		payee_account_name: DF.Data | None
		payee_bic: DF.Data | None
		payee_iban: DF.Data | None
		payment_terms: DF.Table[eInvoicePaymentTerm]
		profile: DF.ReadOnly | None
		purchase_order: DF.Link | None
		sales_invoice: DF.Link | None
		seller_address_line_1: DF.Data | None
		seller_address_line_2: DF.Data | None
		seller_city: DF.Data | None
		seller_country: DF.Link | None
		seller_electronic_address: DF.Data | None
		seller_electronic_address_scheme: DF.Data | None
		seller_name: DF.Data | None
		seller_postcode: DF.Data | None
		seller_tax_id: DF.Data | None
		supplier_invoices_basket: DF.Link | None
		tax_basis_total: DF.Currency
		tax_total: DF.Currency
		taxes: DF.Table[eInvoiceTradeTax]
		total_prepaid: DF.Currency
		validation_errors: DF.Text | None
		validation_warnings: DF.Text | None
	# end: auto-generated types

	def validate(self):
		if self.einvoice_type == "Incoming":
			self.validate_incoming_data()
		elif self.einvoice_type == "Outgoing":
			self.create_outgoing_einvoice()
			self.validate_einvoice()

	def on_update(self):
		if not frappe.db.get_value("Supplier Invoice", dict(einvoice=self.name)):
			self.generate_supplier_invoice()

	def validate_incoming_data(self):
		self.read_values_from_einvoice()
		self.guess_company()
		self.guess_uom()
		self.guess_po_details()

	def create_outgoing_einvoice(self):
		self.einvoice_data = None
		self.map_sales_invoice_to_einvoice()
		self.generate_einvoice()

	def map_sales_invoice_to_einvoice(self):
		self.einvoice_data: EInvoiceMapper = EInvoiceMapper(self)
		self.einvoice_data.run()

	def generate_einvoice(self):
		if not hasattr(self, "einvoice_data") or not self.einvoice_data:
			return

		sales_invoice: SalesInvoice = self.einvoice_data.sales_invoice
		sales_invoice.run_method("before_einvoice_generation")

		profile = EInvoiceProfile(sales_invoice.get("etransaction_profile"))
		generator = EInvoiceGenerator(
			profile=profile,
			invoice=sales_invoice,
			company=self.einvoice_data.company,
			customer=self.einvoice_data.customer,
			seller_address=self.einvoice_data.seller_address,
			buyer_address=self.einvoice_data.buyer_address,
			shipping_address=self.einvoice_data.shipping_address,
			seller_contact=self.einvoice_data.seller_contact,
			buyer_contact=self.einvoice_data.buyer_contact,
		)
		generator.create_einvoice()
		doc = generator.get_einvoice()

		self.einvoice_data.sales_invoice.run_method("after_einvoice_generation")

		self.einvoice_xml = doc.serialize(schema=get_drafthorse_schema(profile))

	def on_submit(self):
		self.add_seller_product_ids_to_items()

	def onload(self):
		if self.docstatus == 0:
			return

	def read_values_from_einvoice(self) -> None:
		if not self.einvoice:
			return

		eInvoiceParser(self).parse_einvoice()

	def guess_company(self):
		if self.company:
			return

		if frappe.db.exists("Company", self.buyer_name):
			self.company = self.buyer_name
		else:
			self.company = get_default_company()

	def guess_uom(self):
		for row in self.items:
			if row.uom:
				continue

			if row.unit_code:
				rec20_3 = get_docnames_for("urn:xoev-de:kosit:codeliste:rec20_3", "UOM", row.unit_code)
				if rec20_3:
					row.uom = rec20_3[0]
				else:
					rec21_3 = get_docnames_for("urn:xoev-de:kosit:codeliste:rec21_3", "UOM", row.unit_code)
					if rec21_3:
						row.uom = rec21_3[0]
			elif row.item:
				stock_uom, purchase_uom = frappe.db.get_value("Item", row.item, ["stock_uom", "purchase_uom"])
				row.uom = purchase_uom or stock_uom


	def guess_po_details(self):
		if not self.purchase_order:
			for pi_row in self.items:
				pi_row.po_detail = None
			return

		purchase_order = frappe.get_doc("Purchase Order", self.purchase_order)
		po_items = [
			frappe._dict(
				name=po_row.name,
				item_code=po_row.item_code,
				unbilled_amount=po_row.amount - po_row.billed_amt,
			)
			for po_row in purchase_order.items
		]
		for pi_row in self.items:
			if pi_row.po_detail and frappe.db.exists(
				"Purchase Order Item", {"name": pi_row.po_detail, "parent": self.purchase_order}
			):
				continue

			for po_row in po_items:
				if po_row.item_code == pi_row.item and po_row.unbilled_amount >= pi_row.total_amount:
					pi_row.po_detail = po_row.name
					po_row.unbilled_amount -= pi_row.total_amount
					break
			else:
				pi_row.po_detail = None

	def add_seller_product_ids_to_items(self):
		if self.einvoice_type == "Incoming":
			return

		for row in self.items:
			try:
				# This is a convenience feature. Failure to update the Item data
				# should not prevent submission of the E Invoice.
				row.add_seller_product_id_to_item(self.supplier)
			except frappe.ValidationError:
				frappe.log_error(
					title="Failed to store Seller Product ID",
					reference_doctype=self.doctype,
					reference_name=self.name,
				)

	def validate_einvoice(self):
		self.validation_errors = ""
		self.validation_warnings = ""

		if not self.profile:
			return

		try:
			xml_string = self.einvoice_xml.decode()
		except Exception:
			msg = _("Cannot create E Invoice.")
			self.validation_errors = msg
			frappe.log_error(msg, reference_doctype=self.doctype, reference_name=self.name)
			return

		try:
			invoice_profile = EInvoiceProfile(self.profile)
			validation_errors, warnings = get_validation_errors(xml_string, invoice_profile)

			if invoice_profile == EInvoiceProfile.XRECHNUNG:
				basic_errors, basic_warnings = get_validation_errors(xml_string, EInvoiceProfile.EN16931)
				validation_errors += basic_errors
				warnings += basic_warnings
		except Exception:
			msg = _("Cannot validate E Invoice schematron.")
			self.validation_errors = msg
			frappe.log_error(msg, reference_doctype=self.doctype, reference_name=self.name)
			return

		if any(validation_errors):
			self.validation_errors += "\n".join(validation_errors)

		if any(warnings):
			self.validation_warnings += "\n".join(warnings)

	def generate_supplier_invoice(self):
		data = IncomingInvoiceDataTransformer(self).get_data()

		doc = frappe.new_doc("Supplier Invoice")
		doc.update(data)
		doc.einvoice = self.name

		return doc.insert(ignore_mandatory=True, ignore_links=True)



@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def po_item_query(doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict, as_dict: bool | None = False):
	item_code = filters.pop("item_code", None)
	purchase_order = filters.pop("parent", None)

	if not purchase_order:
		return []

	purchase_order = frappe.get_cached_doc("Purchase Order", purchase_order)
	purchase_order.check_permission("read")

	results = [
		[
			row.name,
			_("Row {0}").format(row.idx),
			row.item_code,
			row.description[:100] + "..." if len(row.description) > 40 else row.description,
			row.get_formatted("qty") + " " + row.uom,
			row.get_formatted("net_rate") + " / " + row.uom,
		]
		for row in purchase_order.items
		if not item_code or row.item_code == item_code
	]

	if not txt:
		return results

	return [row for row in results if txt in ", ".join(row)]


@frappe.whitelist()
def get_po_item_details(po_detail: str):
	purchase_order_name = frappe.db.get_value("Purchase Order Item", po_detail, "parent")
	purchase_order = frappe.get_cached_doc("Purchase Order", purchase_order_name)
	if not purchase_order.has_permission("read"):
		return {}

	row = purchase_order.getone("items", {"name": po_detail})
	return {
		"item_code": row.item_code,
		"uom": row.uom,
	}



class IncomingInvoiceDataTransformer(InvoiceEntityResolverMixin):
	def __init__(self, invoice_doc):
		self.invoice_doc = invoice_doc

	def get_data(self):
		data = {
			"company": self.get_company(),
			"supplier": self.get_supplier(),
			"supplier_name": self.invoice_doc.seller_name,
			"bill_no": self.invoice_doc.id,
			"bill_date": self.invoice_doc.issue_date,
			"due_date": self.invoice_doc.due_date,
			"currency": self.invoice_doc.currency,
			"supplier_net_amount": self.invoice_doc.line_total,
			"supplier_tax_amount": self.invoice_doc.tax_total,
			"supplier_grand_total": self.invoice_doc.grand_total,
			"vendor_address": self.get_seller_address(),
			"tax_id": self.invoice_doc.seller_tax_id,
			"einvoice": self.invoice_doc.name,
			"ocr_basket": self.invoice_doc.supplier_invoices_basket,
			"items": []
		}

		for item in self.invoice_doc.items:
			data["items"].append({
				"supplier_description": item.product_name,
				"description": item.product_description,
				"supplier_item_code": item.seller_product_id,
				"item_code": item.item,
				"qty": item.billed_quantity,
				"rate": item.net_rate,
				"amount": item.total_amount,
			})

		return data

	def get_seller_address(self):
		address_parts = [
			self.invoice_doc.seller_address_line_1,
			self.invoice_doc.seller_address_line_2,
			self.invoice_doc.seller_postcode,
			self.invoice_doc.seller_city,
			self.invoice_doc.seller_country
		]
		return ", ".join([p for p in address_parts if p])

	def get_buyer_address(self):
		address_parts = [
			self.invoice_doc.buyer_address_line_1,
			self.invoice_doc.buyer_address_line_2,
			self.invoice_doc.buyer_postcode,
			self.invoice_doc.buyer_city,
			self.invoice_doc.buyer_country
		]
		return ", ".join([p for p in address_parts if p])

	def get_supplier(self):
		return self.resolve_supplier(
			seller_name=self.invoice_doc.seller_name,
			tax_id=self.invoice_doc.seller_tax_id
		)

	def get_company(self):
		if self.invoice_doc.company:
			return self.invoice_doc.company
			
		return self.resolve_company(
			receiver_name=self.invoice_doc.buyer_name,
			receiver_address=self.get_buyer_address()
		)