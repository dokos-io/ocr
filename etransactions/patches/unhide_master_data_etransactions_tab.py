import frappe


def execute():
	"""Unhide the eTransactions tab on master-data doctypes.

	The Tab Break custom field definition omits `hidden`, so create_custom_fields(update=True)
	never resets a record that was persisted with hidden=1 on an existing site. Flip it back.
	"""
	for doctype in ("Customer", "Company"):
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": "etransactions_tab"})
		if not name:
			continue

		if frappe.db.get_value("Custom Field", name, "hidden"):
			frappe.db.set_value("Custom Field", name, "hidden", 0, update_modified=False)
			frappe.clear_cache(doctype=doctype)
