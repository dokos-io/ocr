import click

import frappe
from frappe import _

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
	rename_ocr_to_etransactions()
	add_custom_fields()


def rename_ocr_to_etransactions():
	from etransactions.patches.rename_ocr_to_etransactions import execute
	execute()


def before_tests():
	from erpnext.setup.utils import before_tests as erpnext_before_tests

	erpnext_before_tests()


def add_custom_fields():
	click.secho("* Updating eTransactions Custom Fields")
	custom_fields = get_custom_fields()
	create_custom_fields(custom_fields, ignore_validate=frappe.flags.in_patch, update=True)

	for dt in custom_fields:
		frappe.clear_cache(doctype=dt)


def get_custom_fields():
	# Keep for translations
	_("Original Invoice")
	_("Drop a file")
	_("OCR Request")
	_("Original File")
	_("Invoice Extraction")
	_("OCR Request Line Item")

	transactions_fields = [
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
			"read_only": 1,
			"no_copy": 1
		},
		{
			"fieldname": "ocr_original_file",
			"fieldtype": "Link",
			"options": "File",
			"label": "Original File",
			"insert_after": "ocr_request",
			"read_only": 1,
			"fetch_from": "pending_purchase_invoice.file",
			"no_copy": 1
		},
		{
			"fieldname": "pending_purchase_invoice",
			"fieldtype": "Link",
			"options": "Pending Purchase Invoice",
			"label": "Pending Purchase Invoice",
			"insert_after": "ocr_original_file",
			"read_only": 1,
			"no_copy": 1
		},
	]

	return {
		"Purchase Order": transactions_fields,
		"Purchase Invoice": transactions_fields,
		"Purchase Order Item": [
			{
				"fieldname": "ocr_request_line_item",
				"fieldtype": "Link",
				"options": "OCR Line Items Mapping",
				"label": "OCR Request Line Item",
				"insert_after": "supplier_quotation_item",
				"read_only": 1,
				"no_copy": 1
			},
			{
				"fieldname": "pending_purchase_invoice_item",
				"fieldtype": "Link",
				"options": "Pending Purchase Invoice Item",
				"label": "Pending Purchase Invoice Item",
				"insert_after": "ocr_request_line_item",
				"read_only": 1,
				"no_copy": 1
			},
		]
	}