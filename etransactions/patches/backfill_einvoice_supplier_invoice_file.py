import frappe

from etransactions.utils.files import copy_file_to_document


def execute():
	"""Give e-invoice Supplier Invoices the source file their preview needs.

	Only the OCR path ever set `file`, so Supplier Invoices generated from an eInvoice
	showed an empty preview pane. Copy the eInvoice's file onto each of them, the way
	eInvoice.attach_source_file_to() now does at creation time.
	"""
	if not frappe.db.table_exists("Supplier Invoice"):
		return

	invoices = frappe.get_all(
		"Supplier Invoice",
		filters={"einvoice": ("is", "set"), "file": ("in", ("", None))},
		fields=["name", "einvoice"],
	)

	for invoice in invoices:
		source_file = frappe.db.get_value("eInvoice", invoice.einvoice, "einvoice")
		if not source_file or not frappe.db.exists("File", source_file):
			continue

		try:
			file_name = copy_file_to_document(source_file, "Supplier Invoice", invoice.name)
			frappe.db.set_value(
				"Supplier Invoice",
				invoice.name,
				{"file": file_name, "file_url": frappe.db.get_value("File", file_name, "file_url")},
				update_modified=False,
			)
		except Exception:
			continue
