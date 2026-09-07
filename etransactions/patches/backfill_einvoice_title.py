import frappe
from frappe import _


def execute():
	"""Fill the new eInvoice title on records created while title_field was seller_name.

	Records are named by hash, so without a title the list and the breadcrumb fall back
	to that hash — and an incoming flow whose file has not been parsed yet has no seller
	name either, which rendered as the literal "undefined". Mirrors eInvoice.set_title().
	"""
	if not frappe.db.table_exists("eInvoice"):
		return

	einvoices = frappe.get_all(
		"eInvoice",
		filters={"title": ("in", ("", None))},
		fields=["name", "id", "seller_name", "pa_flow_id"],
	)
	for einvoice in einvoices:
		if einvoice.id and einvoice.seller_name:
			title = f"{einvoice.id} · {einvoice.seller_name}"
		elif einvoice.id or einvoice.seller_name:
			title = einvoice.id or einvoice.seller_name
		elif einvoice.pa_flow_id:
			title = _("Incoming flow {0}").format(einvoice.pa_flow_id)
		else:
			title = einvoice.name

		frappe.db.set_value("eInvoice", einvoice.name, "title", title, update_modified=False)
