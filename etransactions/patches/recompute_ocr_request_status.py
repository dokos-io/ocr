import frappe


def execute():
	"""OCR Requests analysed since check_pending_analysis skips analysed requests stayed Pending.

	That hourly job was the only one to set "Analysis Completed" once the analysis was stored.
	The linked Supplier Invoice also never made a request Completed or Closed.
	"""
	for name in frappe.get_all(
		"OCR Request",
		filters={"status": ("in", ["Pending", "Analysis Completed"]), "analysis": ("is", "set")},
		pluck="name",
	):
		doc = frappe.get_doc("OCR Request", name)
		status = doc.status
		doc.set_status()
		if doc.status != status:
			doc.db_set("status", doc.status, update_modified=False)
