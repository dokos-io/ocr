import frappe

def on_trash(doc, method=None):
	unlink_pending_purchase_invoices(doc)

def unlink_pending_purchase_invoices(doc):
	if not doc.pending_purchase_invoice:
		return

	for line in frappe.get_all("Supplier Invoice Item", filters=dict(reference_doctype=doc.doctype, reference_docname=doc.name, parent=doc.pending_purchase_invoice)):
		frappe.db.set_value("Supplier Invoice Item", line.name, "reference_doctype", None)
		frappe.db.set_value("Supplier Invoice Item", line.name, "reference_docname", None)

	frappe.get_doc("Supplier Invoice", doc.pending_purchase_invoice).run_method("set_status", commit=True)