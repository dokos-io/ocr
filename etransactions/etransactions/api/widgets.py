# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _

from etransactions.plateforme_agreee.readiness import (
	_company_row,
	company_check_specs,
	customer_check_specs,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_ADDRESS_FIELDS = ("siret_number", "address_line1", "city", "pincode", "country")
_EMPTY_ADDRESS = dict.fromkeys(_ADDRESS_FIELDS)


def _pct(count: int, total: int) -> int:
	return round(count / total * 100) if total else 0


def _finalize_groups(by_group: dict) -> list:
	"""Sort groups alphabetically and add a computed ready_pct field."""
	groups = sorted(by_group.values(), key=lambda g: g["group"])
	for g in groups:
		g["ready_pct"] = _pct(g["ready"], g["total"])
	return groups


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_customer_readiness_data() -> dict:
	"""
	Aggregated customer readiness data for the FacturX Readiness workspace widget.
	Includes a per-customer-group breakdown.
	"""
	customers = _fetch_customers()
	total = len(customers)
	if not total:
		return {"total": 0, "ready": 0, "ready_pct": 0, "checks": [], "by_group": []}

	_enrich_customer_addresses(customers)

	checks = customer_check_specs()
	counts = {c.key: 0 for c in checks}
	by_group: dict = {}
	ready = 0

	for row in customers:
		is_ready = all(c.passes(row) for c in checks if c.blocking)
		if is_ready:
			ready += 1

		for c in checks:
			if c.passes(row):
				counts[c.key] += 1

		group = row.get("customer_group") or _("(No Group)")
		grp = by_group.setdefault(group, {"group": group, "total": 0, "ready": 0})
		grp["total"] += 1
		if is_ready:
			grp["ready"] += 1

	return {
		"total": total,
		"ready": ready,
		"ready_pct": _pct(ready, total),
		"checks": [c.as_result(counts[c.key], total) for c in checks],
		"by_group": _finalize_groups(by_group),
	}


@frappe.whitelist()
def get_company_readiness_data() -> dict:
	"""Seller-side readiness for the FacturX Readiness workspace widget.

	One row per active company (there are few), evaluated against
	``company_check_specs`` — the missing counterpart of the customer widget.
	"""
	companies = frappe.get_all("Company", pluck="name")
	total = len(companies)
	if not total:
		return {"total": 0, "ready": 0, "ready_pct": 0, "checks": [], "by_group": []}

	checks = company_check_specs()
	counts = {c.key: 0 for c in checks}
	by_group: dict = {}
	ready = 0

	for name in companies:
		row = _company_row(name)
		is_ready = all(c.passes(row) for c in checks if c.blocking)
		if is_ready:
			ready += 1
		for c in checks:
			if c.passes(row):
				counts[c.key] += 1
		by_group[name] = {"group": name, "total": 1, "ready": 1 if is_ready else 0}

	return {
		"total": total,
		"ready": ready,
		"ready_pct": _pct(ready, total),
		"checks": [c.as_result(counts[c.key], total) for c in checks],
		"by_group": _finalize_groups(by_group),
	}


@frappe.whitelist()
def get_item_tax_readiness_data() -> dict:
	"""
	Item tax readiness data for the FacturX Readiness workspace widget.
	Includes a per-item-group breakdown.

	Three checks per item:
	  1. Has Tax Template    — at least one Item Tax row with a template set.
	  2. All Rows Complete   — no tax rows with a missing template (items with
	                           zero rows also fail this check).
	  3. Full Coverage       — a valid template exists for every combination of
	                           Tax Category used by active customers × active Company.
	                           An empty Tax Category counts as "domestic".
	"""
	Item = frappe.qb.DocType("Item")
	items = (
		frappe.qb.from_(Item)
		.select(Item.name.as_("item"), Item.item_group)
		.where((Item.disabled == 0) & (Item.is_sales_item == 1))
		.run(as_dict=True)
	)

	total = len(items)
	if not total:
		return {"total": 0, "ready": 0, "ready_pct": 0, "checks": [], "by_group": []}

	item_names = [i.item for i in items]
	tax_coverage = _fetch_item_tax_coverage(item_names)
	required_pairs = _required_category_company_pairs()

	no_template = 0
	empty_rows = 0
	no_coverage = 0
	ready = 0
	by_group: dict = {}

	for item in items:
		item_taxes = tax_coverage.get(item.item, [])
		row_count = len(item_taxes)
		valid_count = sum(1 for r in item_taxes if r.item_tax_template)

		has_template = row_count > 0
		all_complete = row_count > 0 and valid_count == row_count
		covered_pairs = frozenset(
			(r.tax_category or "", r.company or "")
			for r in item_taxes
			if r.item_tax_template
		)
		full_coverage = not required_pairs or required_pairs.issubset(covered_pairs)
		is_ready = has_template and all_complete and full_coverage

		if not has_template:
			no_template += 1
		if not all_complete:  # also counts items with zero rows (bug fix)
			empty_rows += 1
		if not full_coverage:
			no_coverage += 1
		if is_ready:
			ready += 1

		group = item.get("item_group") or _("(No Group)")
		grp = by_group.setdefault(group, {"group": group, "total": 0, "ready": 0})
		grp["total"] += 1
		if is_ready:
			grp["ready"] += 1

	checks = [
		{
			"key": "has_template",
			"label": _("Has Tax Template"),
			"complete": total - no_template,
			"missing": no_template,
			"total": total,
			"pct": _pct(total - no_template, total),
			"blocking": True,
		},
		{
			"key": "all_complete",
			"label": _("All Rows Complete"),
			"complete": total - empty_rows,
			"missing": empty_rows,
			"total": total,
			"pct": _pct(total - empty_rows, total),
			"blocking": True,
		},
		{
			"key": "full_coverage",
			"label": _("Full Category Coverage"),
			"complete": total - no_coverage,
			"missing": no_coverage,
			"total": total,
			"pct": _pct(total - no_coverage, total),
			"blocking": True,
		},
	]

	return {
		"total": total,
		"ready": ready,
		"ready_pct": _pct(ready, total),
		"checks": checks,
		"by_group": _finalize_groups(by_group),
	}


@frappe.whitelist()
def get_vat_configuration_status() -> dict:
	"""
	Status of the tax-category based VAT configuration for the FacturX Readiness
	workspace widget, with a link to the France VAT Migration Tool.

	Checks:
	  1. Determination    — every active tax category selects a Sales and a Purchase
	                        taxes template, either through a Tax Rule or through the
	                        tax category set on the template itself.
	  2. Customers        — active customers with a tax category.
	  3. Suppliers        — active suppliers with a tax category.
	  4. Addresses        — active addresses with a tax category.
	  5. Item Groups      — item groups (with active items) carrying an item tax
	                        template for every active tax category.
	"""
	categories = frappe.get_all("Tax Category", filters={"disabled": 0}, pluck="name")

	checks = [
		_determination_check(categories),
		_party_tax_category_check("Customer", "customers", _("Customers with Tax Category")),
		_party_tax_category_check("Supplier", "suppliers", _("Suppliers with Tax Category")),
		_party_tax_category_check("Address", "addresses", _("Addresses with Tax Category")),
		_item_group_coverage_check(categories),
	]

	return {
		"categories": len(categories),
		"configured": bool(categories) and all(c["pct"] == 100 for c in checks),
		"checks": checks,
		"tool_route": "/app/vat-configuration-tool",
	}


def _determination_check(categories: list) -> dict:
	"""A category is covered per tax type by a Tax Rule or a tagged taxes template."""
	covered = set()
	if categories:
		for rule in frappe.get_all(
			"Tax Rule",
			filters={"tax_category": ("in", categories), "use_for_shopping_cart": 0},
			fields=["tax_type", "tax_category"],
		):
			covered.add((rule.tax_category, rule.tax_type))

		for tax_type, doctype in (
			("Sales", "Sales Taxes and Charges Template"),
			("Purchase", "Purchase Taxes and Charges Template"),
		):
			for tax_category in frappe.get_all(
				doctype,
				filters={"disabled": 0, "tax_category": ("in", categories)},
				pluck="tax_category",
			):
				covered.add((tax_category, tax_type))

	complete = sum(
		1 for c in categories if (c, "Sales") in covered and (c, "Purchase") in covered
	)
	total = len(categories)
	return {
		"key": "determination",
		"label": _("Determination per Category"),
		"complete": complete,
		"missing": total - complete,
		"total": total,
		"pct": _pct(complete, total),
		"blocking": True,
	}


def _party_tax_category_check(doctype: str, key: str, label: str) -> dict:
	total = frappe.db.count(doctype, {"disabled": 0})
	complete = frappe.db.count(doctype, {"disabled": 0, "tax_category": ("is", "set")})
	return {
		"key": key,
		"label": label,
		"complete": complete,
		"missing": total - complete,
		"total": total,
		"pct": _pct(complete, total),
		"blocking": doctype != "Address",
	}


def _item_group_coverage_check(categories: list) -> dict:
	Item = frappe.qb.DocType("Item")
	groups = {
		row[0]
		for row in (
			frappe.qb.from_(Item)
			.select(Item.item_group)
			.distinct()
			.where(Item.disabled == 0)
			.run()
		)
		if row[0]
	}

	ItemTax = frappe.qb.DocType("Item Tax")
	covered_rows = (
		frappe.qb.from_(ItemTax)
		.select(ItemTax.parent, ItemTax.tax_category)
		.where((ItemTax.parenttype == "Item Group") & (ItemTax.item_tax_template.isnotnull()))
		.run()
	)
	covered: dict = {}
	for parent, tax_category in covered_rows:
		covered.setdefault(parent, set()).add(tax_category or "")

	required = set(categories)
	complete = sum(1 for group in groups if required.issubset(covered.get(group, set())))
	total = len(groups)
	return {
		"key": "item_groups",
		"label": _("Item Groups fully covered"),
		"complete": complete,
		"missing": total - complete,
		"total": total,
		"pct": _pct(complete, total),
		"blocking": True,
	}


# ---------------------------------------------------------------------------
# Private data-fetching helpers
# ---------------------------------------------------------------------------


def _fetch_customers() -> list:
	Customer = frappe.qb.DocType("Customer")
	return (
		frappe.qb.from_(Customer)
		.select(
			Customer.name,
			Customer.customer_group,
			Customer.siren_number,
			Customer.tax_id,
			Customer.customer_primary_contact,
			Customer.email_id,
			Customer.customer_primary_address,
			Customer.etransaction_profile,
			Customer.directory_type,
			Customer.directory_entity_type,
			Customer.directory_query_siren,
			Customer.directory_query_siret,
		)
		.where(Customer.disabled == 0)
		.run(as_dict=True)
	)


def _enrich_customer_addresses(customers: list) -> None:
	"""Attach resolved billing address fields to each customer row in-place."""
	addr_by_name = _fetch_named_addresses(customers)
	fallback_by_customer = _fetch_fallback_addresses(customers)

	for row in customers:
		if row.customer_primary_address and row.customer_primary_address in addr_by_name:
			addr = addr_by_name[row.customer_primary_address]
			row["resolved_address"] = row.customer_primary_address
		elif not row.customer_primary_address and row.name in fallback_by_customer:
			addr = fallback_by_customer[row.name]
			row["resolved_address"] = addr.address_name
		else:
			addr = _EMPTY_ADDRESS
			row["resolved_address"] = None

		for field in _ADDRESS_FIELDS:
			row[field] = addr.get(field)


def _fetch_named_addresses(customers: list) -> dict:
	"""Return a {name: address_row} map for all customer_primary_address values."""
	names = [c.customer_primary_address for c in customers if c.customer_primary_address]
	if not names:
		return {}

	Address = frappe.qb.DocType("Address")
	rows = (
		frappe.qb.from_(Address)
		.select(Address.name, *[getattr(Address, f) for f in _ADDRESS_FIELDS])
		.where((Address.name.isin(names)) & (Address.disabled == 0))
		.run(as_dict=True)
	)
	return {r.name: r for r in rows}


def _fetch_fallback_addresses(customers: list) -> dict:
	"""
	For customers that have no customer_primary_address, look up their primary
	billing address via Dynamic Link (is_primary_address = 1).
	Returns a {customer_name: address_row} map.
	"""
	no_addr = [c.name for c in customers if not c.customer_primary_address]
	if not no_addr:
		return {}

	Address = frappe.qb.DocType("Address")
	DL = frappe.qb.DocType("Dynamic Link")
	rows = (
		frappe.qb.from_(Address)
		.inner_join(DL)
		.on(
			(DL.link_doctype == "Customer")
			& (DL.parenttype == "Address")
			& (DL.parent == Address.name)
			& DL.link_name.isin(no_addr)
		)
		.select(
			DL.link_name.as_("customer"),
			Address.name.as_("address_name"),
			*[getattr(Address, f) for f in _ADDRESS_FIELDS],
		)
		.where((Address.is_primary_address == 1) & (Address.disabled == 0))
		.run(as_dict=True)
	)
	# Keep only the first match per customer (there should only be one primary address)
	result = {}
	for r in rows:
		result.setdefault(r.customer, r)
	return result


def _fetch_item_tax_coverage(item_names: list) -> dict:
	"""
	Return {item_name: [row]} where each row carries item_tax_template,
	tax_category, and the company of the linked Item Tax Template.
	"""
	if not item_names:
		return {}

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
		.run(as_dict=True)
	)
	result: dict = {}
	for r in rows:
		result.setdefault(r.item, []).append(r)
	return result


def _required_category_company_pairs() -> frozenset:
	"""
	Returns the set of (tax_category, company) pairs that every sales item must cover.

	tax_category comes from active customers (empty string = domestic / no category).
	company comes from all companies in the system.
	The empty tax category is always included even if no customer uses it, because
	domestic transactions require a tax configuration.
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
