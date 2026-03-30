import frappe


def execute():
	"""
	Check every ocr_request link and if it doesn't exist anymore, set the field value as None.
	This affects Supplier Invoice, Purchase Order and Purchase Invoice.
	"""
	doctypes = ["Supplier Invoice", "Purchase Order", "Purchase Invoice"]

	for doctype in doctypes:
		# Get all documents that have an ocr_request set
		docs_with_ocr = frappe.get_all(
			doctype,
			filters={"ocr_request": ["is", "set"]},
			fields=["name", "ocr_request"]
		)

		if not docs_with_ocr:
			continue

		# Get all existing OCR Request names to compare
		existing_ocr_requests = set(frappe.get_all("OCR Request", pluck="name"))

		for doc in docs_with_ocr:
			if doc.ocr_request not in existing_ocr_requests:
				# OCR Request doesn't exist, set it to None
				frappe.db.set_value(doctype, doc.name, "ocr_request", None, update_modified=False)
