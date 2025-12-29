import frappe

def execute():
	frappe.db.set_single_value("eTransactions Settings", "ocr_service", "Amazon Textract")