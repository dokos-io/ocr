import frappe


def execute():
	"""Outgoing eInvoices created a Supplier Invoice mirroring our own sale. Delete the
	untouched ones; keep and report any a user already turned into a purchase document."""
	outgoing = frappe.get_all("eInvoice", filters={"einvoice_type": "Outgoing"}, pluck="name")
	if not outgoing:
		return

	for supplier_invoice in frappe.get_all(
		"Supplier Invoice",
		filters={"einvoice": ("in", outgoing), "status": ("!=", "Completed")},
		pluck="name",
	):
		try:
			frappe.delete_doc("Supplier Invoice", supplier_invoice, ignore_permissions=True, force=False)
		except frappe.LinkExistsError:
			frappe.log_error(
				title="Supplier Invoice from an outgoing eInvoice kept",
				message=f"Supplier Invoice {supplier_invoice} is linked to another document and was not deleted.",
				reference_doctype="Supplier Invoice",
				reference_name=supplier_invoice,
			)
