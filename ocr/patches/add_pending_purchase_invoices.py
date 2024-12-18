import frappe

from ocr.install import add_custom_fields

def execute():
	frappe.reload_doc("ocr", "doctype", "Pending Purchase Invoice")

	add_custom_fields()

	for ocr_request in frappe.get_all("OCR Request", filters={"status": ("not in", ("Closed", "Completed")), "docstatus": 0}, order_by="creation asc"):
		if frappe.db.get_value("Purchase Invoice", filters={"docstatus": 1, "ocr_request": ocr_request.name}):
			frappe.db.set_value("OCR Request", ocr_request.name, "status", "Completed", update_modified=False)
			continue

		ocr_request_doc = frappe.get_doc("OCR Request", ocr_request.name)
		pending_purchase_invoice = ocr_request_doc.create_pending_purchase_invoice()

		for dt in ["Purchase Order", "Purchase Invoice"]:
			if docname := frappe.db.get_value(dt, dict(ocr_request=ocr_request.name)):
				frappe.db.set_value(dt, docname, "pending_purchase_invoice", pending_purchase_invoice.name, update_modified=False)

				pending_purchase_invoice.items = []
				target_doc = frappe.get_doc(dt, docname)
				for item in target_doc.items:
					line = frappe.copy_doc(item)
					pending_purchase_invoice.append("items", line)

		pending_purchase_invoice.save()

		if ocr_request_doc.status in ["Purchase Order Created", "Purchase Invoice Created"]:
			frappe.db.set_value("OCR Request", ocr_request.name, "status", "Analysis Completed", update_modified=False)


