import frappe
from frappe.model.rename_doc import rename_doc

def execute():
	if frappe.db.exists("DocType", "OCR Settings") and not frappe.db.exists("DocType", "eTransactions Settings"):
		rename_doc("DocType", "OCR Settings", "eTransactions Settings", force=True)
