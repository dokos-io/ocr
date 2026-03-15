# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt
#
# Customer eInvoice Readiness Report
# ------------------------------------
# Validates that each active customer has the data required for electronic invoicing:
#   - SIREN number and Tax ID (TVA intracommunautaire)
#   - A primary contact with an email address
#     NOTE: the email field on Customer is currently fetched from the primary contact;
#     a dedicated `einvoice_email` custom field is planned and will be pre-filled from
#     the primary contact by default.
#   - A primary billing address carrying a valid SIRET number and all mandatory
#     address components (address_line1, city, pincode, country).

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{
			"label": _("Customer"),
			"fieldname": "customer",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 160,
		},
		{
			"label": _("Customer Name"),
			"fieldname": "customer_name",
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"label": _("SIREN Number"),
			"fieldname": "siren_number",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Tax ID"),
			"fieldname": "tax_id",
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"label": _("Primary Contact"),
			"fieldname": "customer_primary_contact",
			"fieldtype": "Link",
			"options": "Contact",
			"width": 170,
		},
		{
			# Not mandatory. Will be auto-filled from the primary contact once the
			# dedicated `einvoice_email` custom field is added.
			"label": _("Email"),
			"fieldname": "email_id",
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"label": _("Billing Address"),
			"fieldname": "billing_address",
			"fieldtype": "Link",
			"options": "Address",
			"width": 200,
		},
		{
			"label": _("SIRET Number"),
			"fieldname": "siret_number",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("Address Line 1"),
			"fieldname": "address_line1",
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"label": _("City"),
			"fieldname": "city",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Pincode"),
			"fieldname": "pincode",
			"fieldtype": "Data",
			"width": 90,
		},
		{
			"label": _("Country"),
			"fieldname": "country",
			"fieldtype": "Link",
			"options": "Country",
			"width": 120,
		},
		{
			"label": _("Issues"),
			"fieldname": "issues",
			"fieldtype": "Small Text",
			"width": 350,
		},
	]


def get_data(filters):
	conditions = get_conditions(filters)

	customers = frappe.db.sql(
		f"""
		SELECT
			c.name AS customer,
			c.customer_name,
			c.siren_number,
			c.tax_id,
			c.customer_primary_contact,
			c.email_id,
			c.customer_primary_address AS billing_address
		FROM `tabCustomer` c
		WHERE c.disabled = 0
		{conditions}
		ORDER BY c.customer_name
		""",
		filters,
		as_dict=1,
	)

	if not customers:
		return []

	_enrich_with_address_data(customers)

	data = []
	for row in customers:
		issues = _get_issues(row)

		if filters.get("only_with_issues") and not issues:
			continue

		row["issues"] = ", ".join(issues)
		data.append(row)

	return data


def get_conditions(filters):
	conditions = ""
	if filters.get("customer_group"):
		conditions += " AND c.customer_group = %(customer_group)s"
	return conditions


def _enrich_with_address_data(customers):
	"""
	Attach billing address fields to each customer row.

	Resolution order:
	  1. The address referenced by `customer_primary_address` on the Customer.
	  2. Fallback: any Address linked to the customer via Dynamic Link that has
	     `is_primary_address = 1`.
	"""
	# --- step 1: look up all addresses referenced by customer_primary_address ---
	named_addresses = [c.billing_address for c in customers if c.billing_address]
	address_by_name = {}
	if named_addresses:
		rows = frappe.db.sql(
			"""
			SELECT name, siret_number, address_line1, city, pincode, country
			FROM `tabAddress`
			WHERE name IN %(names)s AND disabled = 0
			""",
			{"names": named_addresses},
			as_dict=1,
		)
		address_by_name = {r.name: r for r in rows}

	# --- step 2: fallback via Dynamic Link for customers with no primary address set ---
	customers_without_address = [c.customer for c in customers if not c.billing_address]
	fallback_by_customer = {}
	if customers_without_address:
		rows = frappe.db.sql(
			"""
			SELECT
				dl.link_name AS customer,
				a.name AS address_name,
				a.siret_number,
				a.address_line1,
				a.city,
				a.pincode,
				a.country
			FROM `tabAddress` a
			INNER JOIN `tabDynamic Link` dl
				ON dl.link_doctype = 'Customer'
				AND dl.parenttype = 'Address'
				AND dl.parent = a.name
				AND dl.link_name IN %(customers)s
			WHERE a.is_primary_address = 1
				AND a.disabled = 0
			""",
			{"customers": customers_without_address},
			as_dict=1,
		)
		# Keep only the first match per customer (there should only be one primary address)
		for r in rows:
			if r.customer not in fallback_by_customer:
				fallback_by_customer[r.customer] = r

	# --- merge address data into customer rows ---
	_empty_addr = dict(siret_number=None, address_line1=None, city=None, pincode=None, country=None)

	for row in customers:
		addr = None
		if row.billing_address and row.billing_address in address_by_name:
			addr = address_by_name[row.billing_address]
		elif not row.billing_address and row.customer in fallback_by_customer:
			fallback = fallback_by_customer[row.customer]
			row["billing_address"] = fallback.address_name
			addr = fallback

		src = addr if addr else _empty_addr
		for field in ("siret_number", "address_line1", "city", "pincode", "country"):
			row[field] = src.get(field) if isinstance(src, dict) else getattr(src, field, None)


def _get_issues(row):
	issues = []

	if not row.get("siren_number"):
		issues.append(_("Missing SIREN Number"))

	if not row.get("tax_id"):
		issues.append(_("Missing Tax ID"))

	if not row.get("customer_primary_contact"):
		issues.append(_("No Primary Contact"))

	# Email is not a blocking field — it will be filled automatically from the primary
	# contact once the dedicated `einvoice_email` custom field is available.
	if not row.get("email_id"):
		issues.append(_("No Email (will be auto-filled from primary contact)"))

	if not row.get("billing_address"):
		issues.append(_("No Primary Billing Address"))
	else:
		if not row.get("siret_number"):
			issues.append(_("Missing SIRET Number on billing address"))

		missing = []
		for field, label in (
			("address_line1", _("Address Line 1")),
			("city", _("City")),
			("pincode", _("Pincode")),
			("country", _("Country")),
		):
			if not row.get(field):
				missing.append(label)

		if missing:
			issues.append(_("Incomplete billing address: {0}").format(", ".join(missing)))

	return issues
