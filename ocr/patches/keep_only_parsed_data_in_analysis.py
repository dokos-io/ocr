import frappe

def execute():
	for ocr_request in frappe.get_all("OCR Request"):
		doc = frappe.get_doc("OCR Request", ocr_request.name)
		if doc.analysis:
			analysis = frappe.parse_json(doc.analysis).get("ParsedData", {})
			doc.db_set("analysis", frappe.as_json(analysis))