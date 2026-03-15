# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

from dataclasses import dataclass
from typing import Callable

import frappe
from frappe import _

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
# Check definition
# ---------------------------------------------------------------------------


@dataclass
class _Check:
	"""A single readiness criterion for the widget."""

	key: str
	label: str  # must be set at request time via _()
	blocking: bool
	passes: Callable[[dict], bool]

	def as_result(self, count: int, total: int) -> dict:
		return {
			"key": self.key,
			"label": self.label,
			"complete": count,
			"missing": total - count,
			"total": total,
			"pct": _pct(count, total),
			"blocking": self.blocking,
		}


# ---------------------------------------------------------------------------
# Customer check predicates
# ---------------------------------------------------------------------------


def _siret_ok(r: dict) -> bool:
	return bool(r.get("resolved_address")) and bool(r.get("siret_number"))


def _addr_fields_ok(r: dict) -> bool:
	return bool(r.get("resolved_address")) and all(
		r.get(f) for f in ("address_line1", "city", "pincode", "country")
	)


def _customer_checks() -> list[_Check]:
	"""
	Ordered list of customer readiness checks.
	Called inside the request so _() translations are applied correctly.
	"""
	return [
		_Check("siren", _("SIREN Number"), blocking=True, passes=lambda r: bool(r.get("siren_number"))),
		_Check("tax_id", _("Tax ID"), blocking=True, passes=lambda r: bool(r.get("tax_id"))),
		_Check(
			"contact",
			_("Primary Contact"),
			blocking=True,
			passes=lambda r: bool(r.get("customer_primary_contact")),
		),
		_Check(
			"email",
			_("Email"),
			# Non-blocking — will be auto-filled from the primary contact once the
			# dedicated `einvoice_email` custom field is available.
			blocking=False,
			passes=lambda r: bool(r.get("email_id")),
		),
		_Check(
			"address",
			_("Billing Address"),
			blocking=True,
			passes=lambda r: bool(r.get("resolved_address")),
		),
		_Check("siret", _("SIRET on Address"), blocking=True, passes=_siret_ok),
		_Check("addr_fields", _("Address Fields"), blocking=True, passes=_addr_fields_ok),
	]


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

	checks = _customer_checks()
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
