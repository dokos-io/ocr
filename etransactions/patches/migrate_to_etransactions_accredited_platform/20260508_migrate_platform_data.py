# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

"""
Migration patch: migrate from the old PA Platform / eTransactions Company Settings structure
to the new eTransactions Accredited Platform with per-company, per-transaction-type configuration.

Handles both:
- Fresh installations: no-op (new DocTypes are already correct)
- Existing deployments: migrate PA Platform records and company_settings child rows
"""

import frappe


def execute():
	frappe.reload_doc("eTransactions", "doctype", "eTransactions Accredited Platform")
	frappe.reload_doc("eTransactions", "doctype", "eTransactions Settings")

	_migrate_pa_platform_table()
	_migrate_company_settings()
	_rename_settings_field()
	_update_custom_field_references()

	frappe.clear_cache(doctype="eTransactions Accredited Platform")
	frappe.clear_cache(doctype="eTransactions Settings")
	frappe.clear_cache(doctype="Customer")
	frappe.clear_cache(doctype="Customer Group")


def _migrate_pa_platform_table():
	"""Rename tabPA Platform to tabeTransactions Accredited Platform if it still exists."""
	if not frappe.db.table_exists("PA Platform"):
		return

	frappe.db.sql("""
		UPDATE `tabDocType`
		SET name = 'eTransactions Accredited Platform',
			module = 'eTransactions',
			autoname = 'hash'
		WHERE name = 'PA Platform'
	""")

	if frappe.db.table_exists("PA Platform"):
		frappe.db.sql("RENAME TABLE `tabPA Platform` TO `tabeTransactions Accredited Platform`")

	# Add new columns to existing records if they don't exist yet
	for col, col_type in [
		("company", "VARCHAR(255)"),
		("transaction_type", "VARCHAR(50) DEFAULT 'Both'"),
		("platform_type", "VARCHAR(50) DEFAULT 'Custom'"),
		("client_id", "VARCHAR(255)"),
		("client_secret", "VARCHAR(255)"),
		("auto_send_on_submit", "TINYINT(1) DEFAULT 0"),
		("directory_refresh_days", "INT(11) DEFAULT 15"),
	]:
		if not frappe.db.has_column("eTransactions Accredited Platform", col):
			frappe.db.sql(f"ALTER TABLE `tabeTransactions Accredited Platform` ADD COLUMN `{col}` {col_type}")

	frappe.db.sql("""
		UPDATE `tabCustom Field`
		SET options = 'eTransactions Accredited Platform'
		WHERE options = 'PA Platform'
	""")
	frappe.db.sql("""
		UPDATE `tabCustom Field`
		SET fieldname = 'accredited_platform_override'
		WHERE fieldname = 'pa_platform_override'
	""")


def _migrate_company_settings():
	"""Migrate eTransactions Company Settings child rows into standalone platform records."""
	if not frappe.db.table_exists("eTransactions Company Settings"):
		return

	rows = frappe.db.sql("""
		SELECT company, accredited_platform, client_id, client_secret,
			   auto_send_on_submit, directory_refresh_days
		FROM `tabeTransactions Company Settings`
	""", as_dict=True)

	for row in rows:
		company = row.get("company")
		if not company:
			continue

		existing = frappe.db.get_value(
			"eTransactions Accredited Platform",
			{"company": company},
			"name",
		)

		if existing:
			doc = frappe.get_doc("eTransactions Accredited Platform", existing)
			if not doc.client_id:
				doc.client_id = row.get("client_id")
			if not doc.client_secret:
				doc.client_secret = row.get("client_secret")
			if not doc.directory_refresh_days:
				doc.directory_refresh_days = row.get("directory_refresh_days") or 15
			doc.save(ignore_permissions=True)
		else:
			platform_code = row.get("accredited_platform") or "superpdp"
			platform_type = "SuperPDP" if platform_code == "superpdp" else ("Esalink" if platform_code == "esalink" else "Custom")
			doc = frappe.new_doc("eTransactions Accredited Platform")
			doc.platform_name = f"{platform_type} - {company}"
			doc.platform_type = platform_type
			doc.platform_code = platform_code
			doc.company = company
			doc.transaction_type = "Both"
			doc.client_id = row.get("client_id")
			doc.client_secret = row.get("client_secret")
			doc.auto_send_on_submit = row.get("auto_send_on_submit") or 0
			doc.directory_refresh_days = row.get("directory_refresh_days") or 15
			doc.is_active = 1
			doc.save(ignore_permissions=True)


def _rename_settings_field():
	"""Rename default_platform / default_accredited_platform to default_sales_platform."""
	if frappe.db.has_column("eTransactions Settings", "default_platform"):
		frappe.db.sql("""
			ALTER TABLE `tabeTransactions Settings`
			CHANGE COLUMN `default_platform` `default_sales_platform` VARCHAR(255)
		""")
	elif frappe.db.has_column("eTransactions Settings", "default_accredited_platform"):
		frappe.db.sql("""
			ALTER TABLE `tabeTransactions Settings`
			CHANGE COLUMN `default_accredited_platform` `default_sales_platform` VARCHAR(255)
		""")


def _update_custom_field_references():
	"""Ensure any lingering custom field references are up to date."""
	frappe.db.sql("""
		UPDATE `tabCustom Field`
		SET options = 'eTransactions Accredited Platform'
		WHERE options = 'PA Platform'
	""")
