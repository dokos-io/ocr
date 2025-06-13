import frappe

def execute():
	frappe.db.set_single_value("OCR Settings", "ocr_service", "Amazon Textract")