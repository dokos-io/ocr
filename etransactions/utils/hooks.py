"""Extension points other apps declare in their hooks.py.

``etransactions_seller_electronic_address``
	Dotted paths to ``fn(sales_invoice) -> str | None`` returning the directory
	identifier the invoice is sent from (e.g. ``"123456789_ROUTE1"`` or
	``"0225:123456789_ROUTE1"``). The first non-empty answer replaces the company's
	own electronic address for that invoice (BT-34), e.g. to send each business
	unit's invoices from its own routing code.

``etransactions_incoming_invoice_values``
	Dotted paths to ``fn(einvoice) -> dict | None`` returning header values for the
	Supplier Invoice created from a received e-invoice, e.g. an accounting dimension
	resolved from the buyer's routing code (BT-49). Values of fields that also exist
	on Purchase Invoice are carried over to it.
"""

import frappe


def first_hook_result(hook_name: str, *args):
	"""The first non-empty result of the methods registered for ``hook_name``."""
	for method in frappe.get_hooks(hook_name):
		result = frappe.get_attr(method)(*args)
		if result:
			return result
	return None


def merged_hook_values(hook_name: str, *args) -> dict:
	"""The dicts returned by the methods registered for ``hook_name``, merged in order."""
	values = {}
	for method in frappe.get_hooks(hook_name):
		values.update(frappe.get_attr(method)(*args) or {})
	return values
