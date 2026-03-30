import frappe

def execute():
	if not frappe.get_single_value("eTransactions Settings", "ocr_service"):
		frappe.db.set_single_value("eTransactions Settings", "ocr_service", "Amazon Textract")