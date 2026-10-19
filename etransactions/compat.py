"""Run on both the Dokos ERPNext and the upstream ERPNext.

The Dokos ERPNext moved some document methods into services and the document
mappers into ``mapper`` modules. The upstream ERPNext (and Dokos v5) still has
them on the documents and in the DocType modules. Each helper uses the Dokos
location when it exists and the upstream one otherwise.
"""


def append_taxes_from_master(doc):
	try:
		from erpnext.accounts.services.taxes import TaxService
	except ModuleNotFoundError:
		return doc.append_taxes_from_master()

	return TaxService(doc).append_taxes_from_master()


def append_taxes_from_item_tax_template(doc):
	try:
		from erpnext.accounts.services.taxes import TaxService
	except ModuleNotFoundError:
		return doc.append_taxes_from_item_tax_template()

	return TaxService(doc).append_taxes_from_item_tax_template()


def set_payment_schedule(doc):
	try:
		from erpnext.accounts.services.payment_schedule import PaymentScheduleService
	except ModuleNotFoundError:
		return doc.set_payment_schedule()

	return PaymentScheduleService(doc).set_payment_schedule()


def make_purchase_invoice_from_purchase_order(source_name, target_doc=None):
	try:
		from erpnext.buying.doctype.purchase_order.mapper import make_purchase_invoice
	except ModuleNotFoundError:
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

	return make_purchase_invoice(source_name, target_doc)


def make_purchase_receipt_from_purchase_order(source_name, target_doc=None):
	try:
		from erpnext.buying.doctype.purchase_order.mapper import make_purchase_receipt
	except ModuleNotFoundError:
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

	return make_purchase_receipt(source_name, target_doc)


def set_purchase_order_missing_values(source, target):
	try:
		from erpnext.buying.doctype.purchase_order.mapper import set_missing_values
	except ModuleNotFoundError:
		from erpnext.buying.doctype.purchase_order.purchase_order import set_missing_values

	return set_missing_values(source, target)


def get_purchase_receipt_qty_maps(purchase_receipt):
	"""Return the invoiced and returned quantities per Purchase Receipt Item."""
	try:
		from erpnext.stock.doctype.purchase_receipt.mapper import get_invoiced_qty_map, get_returned_qty_map
	except ModuleNotFoundError:
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
			get_invoiced_qty_map,
			get_returned_qty_map,
		)

	return get_invoiced_qty_map(purchase_receipt), get_returned_qty_map(purchase_receipt)
