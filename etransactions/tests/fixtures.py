# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Master-data seeding shared by the Python and Cypress suites.

An e-invoicing test is only meaningful against a company that is actually in scope:
a SIREN, a VAT number, a seller electronic address and a billing address. That setup
is identical whether it is a Microcks integration test or a Cypress fixture, so it
lives here instead of being copied per harness.

Every function is idempotent — the Cypress fixtures run against a warm site.
"""

import frappe

DEFAULT_SIREN = "824710776"
DEFAULT_TAX_ID = "FR40824710776"


def seed_company(company: str, *, siren: str = DEFAULT_SIREN, tax_id: str = DEFAULT_TAX_ID) -> str:
	"""Make ``company`` a valid e-invoicing seller and return its address name.

	The electronic address guarantees a BT-34 seller endpoint on generated e-invoices;
	without it the readiness check reports the company as not ready and the outbound
	pipeline never starts.
	"""
	frappe.db.set_value(
		"Company",
		company,
		{
			"siren_number": siren,
			"tax_id": tax_id,
			"etransactions_electronic_address_scheme": "0225",
			"etransactions_electronic_address": siren,
			"email": "seller@example.test",
		},
		update_modified=False,
	)
	return seed_company_address(company)


def seed_company_address(company: str) -> str:
	"""Ensure ``company`` has a default billing address (needed for KYC and for UBL).

	Reuses any address already flagged as the company's own rather than matching on a
	title: a second ``is_your_company_address`` row for the same company would make the
	default-address lookup ambiguous.
	"""
	existing = frappe.get_all(
		"Dynamic Link",
		filters={
			"link_doctype": "Company",
			"link_name": company,
			"parenttype": "Address",
		},
		pluck="parent",
	)
	for name in existing:
		if frappe.db.get_value("Address", name, "is_your_company_address"):
			return name

	address = frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": f"{company} eTransactions Address",
			"address_type": "Billing",
			"address_line1": "1 Rue de Rivoli",
			"city": "Paris",
			"pincode": "75001",
			"country": "France",
			"email_id": "seller@example.test",
			"is_your_company_address": 1,
			"links": [{"link_doctype": "Company", "link_name": company}],
		}
	)
	address.flags.ignore_permissions = True
	address.insert(ignore_if_duplicate=True)
	return address.name


def seed_item(item_code: str = "_Test Item 1") -> str:
	"""A non-stock item, so invoices can be built without warehouses or stock ledger."""
	if not frappe.db.exists("Item", item_code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_group": "All Item Groups",
				"is_stock_item": 0,
			}
		).insert(ignore_if_duplicate=True)
	return item_code


def ensure_default_expense_account(company: str) -> str | None:
	"""Give ``company`` a fallback expense account.

	A received e-invoice's lines rarely resolve to a Dokos Item, and a Purchase Invoice
	line without an item has no expense account to inherit — so creating the invoice
	fails on "Expense account is mandatory". Real sites configure this; test sites have
	to be told.
	"""
	if existing := frappe.db.get_value("Company", company, "default_expense_account"):
		return existing

	account = frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 0, "root_type": "Expense"},
		"name",
		order_by="lft",
	)
	if account:
		frappe.db.set_value(
			"Company", company, "default_expense_account", account, update_modified=False
		)
	return account


def clear_platforms(company: str) -> None:
	"""Remove any leftover accredited platforms for ``company``.

	Some provisioning paths call ``frappe.db.commit()``, which escapes the per-test
	rollback, so a prior run can leave committed rows that make a fresh registration
	look 'existing'. Clearing keeps runs order-independent and re-runnable.
	"""
	for name in frappe.get_all(
		"eTransactions Accredited Platform", filters={"company": company}, pluck="name"
	):
		frappe.delete_doc(
			"eTransactions Accredited Platform", name, force=True, ignore_permissions=True
		)
