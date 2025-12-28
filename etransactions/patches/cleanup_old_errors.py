import frappe

def execute():
	for request in frappe.get_all("OCR Request", filters={"error": ("is", "set")}, fields=["name", "error"]):
		if request.error not in ["stale", "no result", "no file"]:
			doc = frappe.get_doc("OCR Request", request.name)
			doc.reset_status_and_error()