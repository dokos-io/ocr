import frappe

from erpnext.stock.get_item_details import get_item_details as _get_item_details

@frappe.whitelist()
def get_item_details(args, doc=None, for_validate=False, overwrite_warehouse=True):
	item_details = _get_item_details(args, doc, for_validate, overwrite_warehouse)

	if (frappe.parse_json(doc) or {}).get("ocr_request"):
		doc_values = frappe.parse_json(args) or {}
		if doc_values:
			item_details["price_list_rate"] = doc_values.get("net_rate")

	return item_details