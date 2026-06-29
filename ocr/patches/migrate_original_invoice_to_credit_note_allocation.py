import frappe
from frappe.utils import flt


def execute():
	"""Migrate the removed ``original_invoice`` single-invoice return flow into one
	``credit_note_allocations`` row per Pending Purchase Invoice.

	The ``original_invoice`` field has been removed from the doctype, but Frappe does
	not drop the underlying column, so we read it directly from the table. Rows are
	inserted with raw SQL to avoid re-running ``validate()`` on already-completed
	documents. Idempotent: invoices that already carry an allocation row are skipped.
	"""
	if not frappe.db.has_column("Pending Purchase Invoice", "original_invoice"):
		return

	ppi = frappe.qb.DocType("Pending Purchase Invoice")
	rows = (
		frappe.qb.from_(ppi)
		.select(ppi.name, ppi.original_invoice, ppi.net_total)
		.where(ppi.original_invoice.notnull() & (ppi.original_invoice != ""))
	).run(as_dict=True)

	for row in rows:
		if not frappe.db.exists("Purchase Invoice", row.original_invoice):
			continue

		if frappe.db.exists(
			"Pending Purchase Invoice Credit Note Allocation", {"parent": row.name}
		):
			continue

		outstanding = frappe.db.get_value(
			"Purchase Invoice", row.original_invoice, "outstanding_amount"
		)

		frappe.get_doc(
			{
				"doctype": "Pending Purchase Invoice Credit Note Allocation",
				"name": frappe.generate_hash(length=10),
				"parent": row.name,
				"parenttype": "Pending Purchase Invoice",
				"parentfield": "credit_note_allocations",
				"idx": 1,
				"purchase_invoice": row.original_invoice,
				"allocated_amount": abs(flt(row.net_total)),
				"outstanding_amount": flt(outstanding),
			}
		).db_insert()
