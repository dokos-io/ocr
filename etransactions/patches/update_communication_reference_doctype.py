import frappe

def execute():
	# Update reference_doctype
	communications = frappe.get_all(
		"Communication",
		filters={"reference_doctype": "OCR Purchase Invoice Basket"}
	)

	for d in communications:
		frappe.db.set_value("Communication", d.name, "reference_doctype", "Supplier Invoices Basket", update_modified=False)

	# Update link_doctype
	link_communications = frappe.get_all(
		"Communication Link",
		filters={"link_doctype": "OCR Purchase Invoice Basket"}
	)

	for d in link_communications:
		frappe.db.set_value("Communication Link", d.name, "link_doctype", "Supplier Invoices Basket", update_modified=False)
