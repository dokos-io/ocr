import frappe

from etransactions.etransactions.doctype.supplier_invoice.processing_guide import get_guide_status


def execute():
	"""Fill the new processing status, and mark the lines copied from an order."""
	item = frappe.qb.DocType("Supplier Invoice Item")
	(
		frappe.qb.update(item)
		.set(item.item_match, "From Order")
		.where(item.reference_docname.isnotnull() & (item.reference_docname != ""))
		.where(item.item_code.isnotnull() & (item.item_code != ""))
		.run()
	)

	frappe.db.set_value(
		"Supplier Invoice", {"status": "Closed"}, "guide_status", "Closed", update_modified=False
	)
	for name in frappe.get_all("Supplier Invoice", filters={"status": ("!=", "Closed")}, pluck="name"):
		try:
			doc = frappe.get_doc("Supplier Invoice", name)
			doc.db_set("guide_status", get_guide_status(doc), update_modified=False)
		except Exception:
			frappe.log_error(
				title="Supplier Invoice guide status patch",
				reference_doctype="Supplier Invoice",
				reference_name=name,
			)
