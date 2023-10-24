import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_migrate():
	make_custom_fields(True)

def make_custom_fields(update=True):
	custom_fields = {
		"Purchase Invoice": [
			dict(
				fieldname="ocr_tab",
				label="Invoice Extraction",
				fieldtype="Tab Break",
				insert_after="connections_tab"
			),
			dict(
				fieldname="ocr_html",
				fieldtype="HTML",
				insert_after="ocr_tab",
			),
		],
	}

	create_custom_fields(custom_fields, ignore_validate=frappe.flags.in_patch, update=update)