import click

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def after_install():
	add_custom_fields()


def add_custom_fields():
	click.secho("* Updating OCR Custom Fields")
	custom_fields = get_custom_fields()
	create_custom_fields(custom_fields, ignore_validate=frappe.flags.in_patch, update=True)

	for dt in custom_fields:
		frappe.clear_cache(doctype=dt)


def get_custom_fields():
	return {
		"Purchase Invoice": [
			{
				"fieldname": "ocr_tab",
				"fieldtype": "Tab Break",
				"label": "Original Invoice",
				"depends_on": "eval:doc.ocr_original_file",
				"insert_after": "connections_tab"
			},
			{
				"fieldname": "ocr_html",
				"fieldtype": "HTML",
				"label": "Drop a file",
				"insert_after": "ocr_tab",
			},
			{
				"fieldname": "ocr_request",
				"fieldtype": "Link",
				"options": "OCR Request",
				"label": "OCR Request",
				"insert_after": "ocr_html",
				"read_only": 1
			},
			{
				"fieldname": "ocr_original_file",
				"fieldtype": "Link",
				"options": "File",
				"label": "Original File",
				"insert_after": "ocr_request",
				"read_only": 1,
				"fetch_from": "ocr_request.file"
			},
		],
		"Supplier": [
			{
				"fieldname": "ocr_section",
				"fieldtype": "Section Break",
				"label": "Invoice Extraction",
				"insert_after": "release_date"
			},
			{
				"fieldname": "ocr_pi_creation_mode",
				"fieldtype": "Select",
				"options": "\nGet items from the OCR analysis\nGet items from purchase orders recognized by the OCR\nGet items from any open purchase order linked to the recognized supplier",
				"label": "Creation Mode",
				"insert_after": "ocr_section",
				"description": "If not set, the creation mode defined in the OCR settings will prevail.",
				"translatable": 0,
			},
		]
	}