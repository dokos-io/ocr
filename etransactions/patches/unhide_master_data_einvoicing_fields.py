import frappe


def execute():
	"""Unhide the e-invoicing master-data fields edited natively on the form.

	The readiness wizard was removed in favour of native fields plus a status
	indicator, so these fields no longer carry `hidden` in their definition. But
	create_custom_fields(update=True) never resets a record persisted with
	hidden=1 on an existing site, so flip the stored value back here.
	"""
	fields = {
		"Customer": (
			"etransaction_profile",
			"etransactions_buyer_reference",
			"etransactions_contract_reference",
			"etransactions_electronic_address_scheme",
			"etransactions_electronic_address",
			"pa_directory_section",
			"directory_entity_type",
			"directory_name",
			"directory_closed",
			"pa_directory_col_break",
			"directory_update_date",
			"default_directory_line",
			"directory_type",
			"accredited_platform_override",
		),
		"Supplier": (
			"etransactions_electronic_address_scheme",
			"etransactions_electronic_address",
		),
	}

	for doctype, fieldnames in fields.items():
		cleared = False
		for fieldname in fieldnames:
			name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname})
			if not name:
				continue
			if frappe.db.get_value("Custom Field", name, "hidden"):
				frappe.db.set_value("Custom Field", name, "hidden", 0, update_modified=False)
				cleared = True
		if cleared:
			frappe.clear_cache(doctype=doctype)
