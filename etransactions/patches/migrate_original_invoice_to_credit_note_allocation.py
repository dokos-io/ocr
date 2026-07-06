import frappe
from frappe.utils import flt


def execute():
	"""Migrate the removed ``original_invoice`` single-invoice return flow into one
	``credit_note_allocations`` row per Supplier Invoice.

	The ``original_invoice`` field has been removed from the doctype, but Frappe does
	not drop the underlying column, so we read it directly from the table. Rows are
	inserted with raw SQL to avoid re-running ``validate()`` on already-completed
	documents. Idempotent: invoices that already carry an allocation row are skipped.
	"""
	if not frappe.db.has_column("Supplier Invoice", "original_invoice"):
		return

	si = frappe.qb.DocType("Supplier Invoice")
	rows = (
		frappe.qb.from_(si)
		.select(si.name, si.original_invoice, si.net_total)
		.where(si.original_invoice.notnull() & (si.original_invoice != ""))
	).run(as_dict=True)

	for row in rows:
		if not frappe.db.exists("Purchase Invoice", row.original_invoice):
			continue

		if frappe.db.exists(
			"Supplier Invoice Credit Note Allocation", {"parent": row.name}
		):
			continue

		invoice_amount = frappe.db.get_value(
			"Purchase Invoice", row.original_invoice, "grand_total"
		)

		frappe.get_doc(
			{
				"doctype": "Supplier Invoice Credit Note Allocation",
				"name": frappe.generate_hash(length=10),
				"parent": row.name,
				"parenttype": "Supplier Invoice",
				"parentfield": "credit_note_allocations",
				"idx": 1,
				"purchase_invoice": row.original_invoice,
				"allocated_amount": abs(flt(row.net_total)),
				"invoice_amount": flt(invoice_amount),
			}
		).db_insert()
