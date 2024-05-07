import frappe

def execute():
	"""Create more specific statuses for OCR Request"""
	for request in frappe.get_all("OCR Request", filters={"status": "Transaction Matched"}):
		frappe.db.set_value("OCR Request", request.name, "status", "Purchase Invoice Created", update_modified=False)
