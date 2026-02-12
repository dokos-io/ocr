import frappe
from frappe.model.rename_doc import rename_doc

def execute():
	if frappe.db.exists("DocType", "OCR Settings") and not frappe.db.exists("DocType", "eTransactions Settings"):
		rename_doc("DocType", "OCR Settings", "eTransactions Settings", force=True)


	if frappe.db.exists("DocType", "OCR Basket") and not frappe.db.exists("DocType", "eTransactions Settings"):
		rename_doc("DocType", "OCR Basket", "Supplier Invoices Basket", force=True)


	if frappe.db.exists("DocType", "Pending Purchase Invoice") and not frappe.db.exists("DocType", "eTransactions Settings"):
		rename_doc("DocType", "Pending Purchase Invoice", "Supplier Invoice", force=True)


	if frappe.db.exists("DocType", "Pending Purchase Invoice Item") and not frappe.db.exists("DocType", "eTransactions Settings"):
		rename_doc("DocType", "Pending Purchase Invoice Item", "Supplier Invoice Item", force=True)
