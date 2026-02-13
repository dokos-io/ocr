import frappe

def on_trash(doc, method=None):
	unlink_supplier_invoices(doc)

def unlink_supplier_invoices(doc):
	if not doc.supplier_invoice:
		return

	for line in frappe.get_all("Supplier Invoice Item", filters=dict(reference_doctype=doc.doctype, reference_docname=doc.name, parent=doc.supplier_invoice)):
		frappe.db.set_value("Supplier Invoice Item", line.name, "reference_doctype", None)
		frappe.db.set_value("Supplier Invoice Item", line.name, "reference_docname", None)

	frappe.get_doc("Supplier Invoice", doc.supplier_invoice).run_method("set_status", commit=True)