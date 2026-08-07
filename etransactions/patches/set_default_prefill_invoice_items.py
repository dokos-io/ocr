import frappe


def execute():
	"""Turn item-line prefill on for existing sites.

	A Check field's default only applies to documents created after it exists, and
	eTransactions Settings is a Single that every site already has — so without this the
	feature would ship switched off everywhere it is most useful.
	"""
	frappe.db.set_single_value("eTransactions Settings", "prefill_invoice_items", 1)
