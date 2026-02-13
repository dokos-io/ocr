import frappe
from frappe.model.rename_doc import rename_doc
from frappe.model.utils.rename_field import rename_field

def execute():
	if frappe.db.exists("DocType", "OCR Settings") and not frappe.db.exists("DocType", "eTransactions Settings"):
		rename_doc("DocType", "OCR Settings", "eTransactions Settings", force=True)


	if frappe.db.exists("DocType", "OCR Basket") and not frappe.db.exists("DocType", "eTransactions Settings"):
		rename_doc("DocType", "OCR Basket", "Supplier Invoices Basket", force=True)


	if frappe.db.exists("DocType", "Pending Purchase Invoice") and not frappe.db.exists("DocType", "eTransactions Settings"):
		rename_doc("DocType", "Pending Purchase Invoice", "Supplier Invoice", force=True)


	if frappe.db.exists("DocType", "Pending Purchase Invoice Item") and not frappe.db.exists("DocType", "eTransactions Settings"):
		rename_doc("DocType", "Pending Purchase Invoice Item", "Supplier Invoice Item", force=True)

	rename_field("Purchase Order", "pending_purchase_invoice", "supplier_invoice")
	rename_field("Purchase Order Item", "pending_purchase_invoice_item", "supplier_invoice_item")
	rename_field("Purchase Invoice", "pending_purchase_invoice", "supplier_invoice")