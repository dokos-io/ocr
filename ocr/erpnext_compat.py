"""Calls to ERPNext that moved between version-16 and develop.

ERPNext develop moved the order and receipt mappers into `mapper.py` modules and the
tax and payment schedule methods into `erpnext.accounts.services`. OCR develop runs
on both versions, so each helper uses the develop location when it exists and the
version-16 location otherwise.
"""

try:
	from erpnext.buying.doctype.purchase_order.mapper import (
		make_purchase_invoice as make_purchase_invoice_from_po,
		make_purchase_receipt,
		set_missing_values as set_purchase_order_missing_values,
	)
except ImportError:
	from erpnext.buying.doctype.purchase_order.purchase_order import (
		make_purchase_invoice as make_purchase_invoice_from_po,
		make_purchase_receipt,
		set_missing_values as set_purchase_order_missing_values,
	)

try:
	from erpnext.stock.doctype.purchase_receipt.mapper import get_invoiced_qty_map, get_returned_qty_map
except ImportError:
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import get_invoiced_qty_map, get_returned_qty_map

try:
	from erpnext.accounts.services.payment_schedule import PaymentScheduleService
	from erpnext.accounts.services.taxes import TaxService
except ImportError:
	PaymentScheduleService = TaxService = None


__all__ = [
	"append_taxes_from_item_tax_template",
	"append_taxes_from_master",
	"get_invoiced_qty_map",
	"get_returned_qty_map",
	"make_purchase_invoice_from_po",
	"make_purchase_receipt",
	"set_payment_schedule",
	"set_purchase_order_missing_values",
]


def append_taxes_from_master(doc):
	if TaxService:
		TaxService(doc).append_taxes_from_master()
	else:
		doc.append_taxes_from_master()


def append_taxes_from_item_tax_template(doc):
	if TaxService:
		TaxService(doc).append_taxes_from_item_tax_template()
	else:
		doc.append_taxes_from_item_tax_template()


def set_payment_schedule(doc):
	if PaymentScheduleService:
		PaymentScheduleService(doc).set_payment_schedule()
	else:
		doc.set_payment_schedule()
