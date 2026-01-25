import click

import frappe

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
	from etransactions.overrides.custom_fields import CUSTOM_FIELDS
	return CUSTOM_FIELDS