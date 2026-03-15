# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt
#
# Item Tax Readiness Report
# -------------------------
# Lists all active sales items and validates their tax configuration:
#   - Has at least one Item Tax Template assigned.
#   - All tax rows have a template set (no empty rows).
#   - Covers every combination of Tax Category used by active customers ×
#     active Company.  An empty Tax Category counts as "domestic".

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
			"label": _("Item"),
			"fieldname": "item",
			"fieldtype": "Link",
			"options": "Item",
			"width": 160,
		},
		{
			"label": _("Item Name"),
			"fieldname": "item_name",
			"fieldtype": "Data",
			"width": 220,
		},
		{
			"label": _("Item Group"),
			"fieldname": "item_group",
			"fieldtype": "Link",
			"options": "Item Group",
			"width": 140,
		},
		{
			"label": _("Tax Templates"),
			"fieldname": "tax_templates",
			"fieldtype": "Small Text",
			"width": 280,
		},
		{
			"label": _("Missing Coverage"),
			"fieldname": "missing_coverage",
			"fieldtype": "Small Text",
			"width": 300,
		},
		{
			"label": _("Issues"),
			"fieldname": "issues",
			"fieldtype": "Small Text",
			"width": 250,
		},
	]


def get_data(filters):
	Item = frappe.qb.DocType("Item")
	query = (
		frappe.qb.from_(Item)
		.select(Item.name.as_("item"), Item.item_name, Item.item_group)
		.where((Item.disabled == 0) & (Item.is_sales_item == 1))
		.orderby(Item.item_group, Item.item_name)
	)
	if filters.get("item_group"):
		query = query.where(Item.item_group == filters.item_group)

	items = query.run(as_dict=True)
	if not items:
		return []

	required_pairs = _get_required_pairs()
	_enrich_with_tax_data(items)

	data = []
	for row in items:
		issues = _get_issues(row, required_pairs)

		if filters.get("only_without_taxes") and not issues:
			continue

		row["missing_coverage"] = _format_missing_coverage(row, required_pairs)
		row["issues"] = ", ".join(issues)
		data.append(row)

	return data


# ---------------------------------------------------------------------------
# Coverage context
# ---------------------------------------------------------------------------


def _get_required_pairs() -> frozenset:
	"""
	Returns the set of (tax_category, company) pairs every item must cover.

	tax_category: all distinct values from active customers (empty = domestic).
	company:      all companies in the system.
	The empty category is always included even if no customer currently uses it.
	"""
	Customer = frappe.qb.DocType("Customer")
	cat_rows = (
		frappe.qb.from_(Customer)
		.select(Customer.tax_category)
		.where(Customer.disabled == 0)
		.distinct()
		.run()
	)
	required_categories = frozenset({row[0] or "" for row in cat_rows} | {""})

	Company = frappe.qb.DocType("Company")
	comp_rows = frappe.qb.from_(Company).select(Company.name).run()
	required_companies = frozenset(row[0] for row in comp_rows)

	return frozenset(
		(cat, comp) for cat in required_categories for comp in required_companies
	)


# ---------------------------------------------------------------------------
# Data enrichment
# ---------------------------------------------------------------------------


def _enrich_with_tax_data(items: list) -> None:
	"""
	Fetch all Item Tax rows (with the company of the linked template) for the
	given items and attach them as `_tax_rows` and `tax_templates`.
	"""
	item_names = [r.item for r in items]

	ItemTax = frappe.qb.DocType("Item Tax")
	ITT = frappe.qb.DocType("Item Tax Template")
	rows = (
		frappe.qb.from_(ItemTax)
		.left_join(ITT)
		.on(ITT.name == ItemTax.item_tax_template)
		.select(
			ItemTax.parent.as_("item"),
			ItemTax.item_tax_template,
			ItemTax.tax_category,
			ITT.company,
		)
		.where((ItemTax.parenttype == "Item") & ItemTax.parent.isin(item_names))
		.orderby(ItemTax.parent, ItemTax.idx)
		.run(as_dict=True)
	)

	taxes_by_item: dict = {}
	for r in rows:
		taxes_by_item.setdefault(r.item, []).append(r)

	for row in items:
		tax_rows = taxes_by_item.get(row.item, [])
		row["_tax_rows"] = tax_rows
		row["tax_templates"] = ", ".join(
			t.item_tax_template for t in tax_rows if t.item_tax_template
		)


# ---------------------------------------------------------------------------
# Issue detection
# ---------------------------------------------------------------------------


def _get_issues(row: dict, required_pairs: frozenset) -> list:
	issues = []
	tax_rows = row.get("_tax_rows", [])

	if not tax_rows:
		issues.append(_("No item tax template assigned"))
	elif any(not t.get("item_tax_template") for t in tax_rows):
		issues.append(_("Tax row with no template"))

	if required_pairs:
		missing = required_pairs - _covered_pairs(tax_rows)
		if missing:
			issues.append(
				_("{0} tax category / company combination(s) not covered").format(len(missing))
			)

	return issues


def _format_missing_coverage(row: dict, required_pairs: frozenset) -> str:
	"""
	Returns a human-readable list of (tax_category, company) pairs that are
	not yet covered by the item's tax rows, e.g. "My Company / No Category".
	"""
	if not required_pairs:
		return ""

	missing = required_pairs - _covered_pairs(row.get("_tax_rows", []))
	if not missing:
		return ""

	parts = []
	for cat, comp in sorted(missing):
		cat_label = cat if cat else _("No Category")
		parts.append(f"{comp} / {cat_label}")
	return ", ".join(parts)


def _covered_pairs(tax_rows: list) -> frozenset:
	"""Returns the set of (tax_category, company) pairs covered by the given rows."""
	return frozenset(
		(t.get("tax_category") or "", t.get("company") or "")
		for t in tax_rows
		if t.get("item_tax_template")
	)
