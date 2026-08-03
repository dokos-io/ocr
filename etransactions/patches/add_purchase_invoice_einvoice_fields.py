import frappe


def execute():
	"""Create the eInvoice reference fields on Purchase Invoice and backfill them.

	The e-invoice a purchase came from used to be reachable only through a two-hop
	lookup (Purchase Invoice -> Supplier Invoice -> eInvoice), which no link field, no
	connection and no fetch_from could follow. Existing invoices keep that history, so
	the new field is populated from the same two hops once.
	"""
	from etransactions.install import add_custom_fields

	add_custom_fields()

	purchase_invoice = frappe.qb.DocType("Purchase Invoice")
	supplier_invoice = frappe.qb.DocType("Supplier Invoice")

	rows = (
		frappe.qb.from_(purchase_invoice)
		.join(supplier_invoice)
		.on(purchase_invoice.supplier_invoice == supplier_invoice.name)
		.select(purchase_invoice.name, supplier_invoice.einvoice)
		.where(supplier_invoice.einvoice.notnull())
		.where(purchase_invoice.einvoice.isnull())
	).run(as_dict=True)

	for row in rows:
		frappe.db.set_value(
			"Purchase Invoice", row.name, "einvoice", row.einvoice, update_modified=False
		)
