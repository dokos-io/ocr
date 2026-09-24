import frappe


def execute():
	"""OCR Requests analysed after a failed attempt kept the old error, and so stayed in Error."""
	for name in frappe.get_all(
		"OCR Request",
		filters={"status": "Error", "error": ("is", "set"), "analysis": ("is", "set")},
		pluck="name",
	):
		doc = frappe.get_doc("OCR Request", name)
		doc.db_set("error", None, update_modified=False)
		doc.set_status()
		doc.db_set("status", doc.status, update_modified=False)
