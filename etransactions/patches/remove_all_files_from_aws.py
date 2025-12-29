import frappe

def execute():
	for request in frappe.get_all("OCR Request", filters={"job": ("is", "set")}):
		doc = frappe.get_doc("OCR Request", request.name)
		doc.delete_remote_file(False)