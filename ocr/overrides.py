import frappe

from erpnext.stock.get_item_details import get_item_details as _get_item_details

@frappe.whitelist()
def get_item_details(args, doc=None, for_validate=False, overwrite_warehouse=True):
	"""
	This function doesn't allow 
	"""

	doc_values = frappe.parse_json(args)
	item_details = _get_item_details(args, doc, for_validate, overwrite_warehouse)
	if frappe.parse_json(doc).get("ocr_request"):
		item_details["price_list_rate"] = doc_values.get("net_rate")

	return item_details