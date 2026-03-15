import click

import frappe

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import now_datetime
from frappe.model.sync import sync_for


def after_install():
	rename_ocr_to_etransactions()
	frappe.delete_doc("Data Extraction", "eTransactions", ignore_missing=True, force=True)
	sync_for("etransactions", force=True, reset_permissions=True)
	add_custom_fields()


def rename_ocr_to_etransactions():
	from etransactions.patches.rename_ocr_to_etransactions import execute
	execute()


def before_tests():
	frappe.clear_cache()
	# complete setup if missing
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	if not frappe.db.a_row_exists("Company"):
		current_year = now_datetime().year
		setup_complete(
			{
				"currency": "USD",
				"full_name": "Test User",
				"company_name": "Wind Power LLC",
				"timezone": "Europe/Paris",
				"company_abbr": "DK",
				"industry": "Manufacturing",
				"country": "France",
				"fy_start_date": f"{current_year}-01-01",
				"fy_end_date": f"{current_year}-12-31",
				"language": "english",
				"email": "test@dokos.io",
				"password": "test",
				"chart_of_accounts": "Plan Comptable Général",
			}
		)


def add_custom_fields():
	click.secho("* Updating eTransactions Custom Fields")
	custom_fields = get_custom_fields()
	create_custom_fields(custom_fields, ignore_validate=frappe.flags.in_patch, update=True)

	for dt in custom_fields:
		frappe.clear_cache(doctype=dt)


def get_custom_fields():
	from etransactions.overrides.custom_fields import CUSTOM_FIELDS
	return CUSTOM_FIELDS