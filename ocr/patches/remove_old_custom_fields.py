import frappe

def execute():
	frappe.delete_doc("Custom Field", "Supplier-ocr_pi_creation_mode", ignore_missing=True)
	frappe.delete_doc("Custom Field", "Supplier-ocr_section", ignore_missing=True)