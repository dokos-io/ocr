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
	}