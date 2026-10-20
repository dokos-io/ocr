# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Item tax template coverage, resolved the way ERPNext resolves it on a sales line.

For one (tax category, company) pair, ERPNext looks at the item's own Item Tax rows
(or the rows of its variant template), then at its item group, then at each ancestor
group (`erpnext.stock.get_item_details.get_item_tax_template`). A row only counts when
its template is enabled, belongs to the company, is not reserved for purchases and
carries the same tax category.
"""

from typing import NamedTuple

import frappe

DOMESTIC = ""  # an empty tax category means a domestic sale


class ItemTaxStatus(NamedTuple):
	has_template: bool
	all_complete: bool
	full_coverage: bool

	@property
	def is_ready(self) -> bool:
		return self.has_template and self.all_complete and self.full_coverage


def einvoicing_companies() -> list[str]:
	"""Companies that issue French e-invoices; every company when none is in France."""
	companies = frappe.get_all("Company", fields=["name", "country"])
	french = [c.name for c in companies if c.country == "France"]
	return french or [c.name for c in companies]


def required_pairs(categories) -> frozenset:
	"""Every (tax category, company) pair to cover, the domestic category included."""
	companies = einvoicing_companies()
	return frozenset(
		(category or DOMESTIC, company) for category in {DOMESTIC, *categories} for company in companies
	)


class ItemTaxResolver:
	"""Load every Item Tax row once and answer coverage questions in memory."""

	def __init__(self):
		self._templates = {
			t.name: t
			for t in frappe.get_all(
				"Item Tax Template", fields=["name", "company", "disabled", "applicable_for"]
			)
		}
		self._rows = self._load_rows()
		self._parent_group = {
			g.name: g.parent_item_group
			for g in frappe.get_all("Item Group", fields=["name", "parent_item_group"])
		}
		self._group_levels: dict = {}
		self._group_status: dict = {}

	def item_status(self, item: str, item_group: str, variant_of: str | None, required) -> ItemTaxStatus:
		own_rows = self._own_rows(item, variant_of)
		if own_rows:
			return self._status([own_rows, *self.group_levels(item_group)], required)

		# Most items carry no rows of their own: their status is the group's
		key = (item_group, required)
		if key not in self._group_status:
			self._group_status[key] = self._status(self.group_levels(item_group), required)
		return self._group_status[key]

	def group_covers(self, item_group: str, required) -> bool:
		return self._covers(self.group_levels(item_group), required)

	def group_levels(self, item_group: str | None) -> list[list]:
		"""Row lists of the group and of its ancestors, nearest first."""
		if item_group not in self._group_levels:
			levels, seen, group = [], set(), item_group
			while group and group not in seen:
				seen.add(group)
				if rows := self._rows.get(("Item Group", group)):
					levels.append(rows)
				group = self._parent_group.get(group)
			self._group_levels[item_group] = levels
		return self._group_levels[item_group]

	def _own_rows(self, item: str, variant_of: str | None) -> list:
		rows = self._rows.get(("Item", item))
		if not rows and variant_of:
			rows = self._rows.get(("Item", variant_of))
		return rows or []

	def _status(self, levels: list[list], required) -> ItemTaxStatus:
		rows = [row for level in levels for row in level]
		return ItemTaxStatus(
			has_template=any(row.item_tax_template for row in rows),
			all_complete=bool(rows) and all(row.item_tax_template for row in rows),
			full_coverage=self._covers(levels, required),
		)

	def _covers(self, levels: list[list], required) -> bool:
		return all(
			any(self._applies(row, category, company) for level in levels for row in level)
			for category, company in required
		)

	def _applies(self, row, category: str, company: str) -> bool:
		template = self._templates.get(row.item_tax_template)
		return (
			template is not None
			and not template.disabled
			and template.company == company
			and template.applicable_for in (None, "", "Sales")
			and (row.tax_category or DOMESTIC) == category
		)

	@staticmethod
	def _load_rows() -> dict:
		ItemTax = frappe.qb.DocType("Item Tax")
		rows = (
			frappe.qb.from_(ItemTax)
			.select(ItemTax.parenttype, ItemTax.parent, ItemTax.item_tax_template, ItemTax.tax_category)
			.where(ItemTax.parenttype.isin(["Item", "Item Group"]))
			.run(as_dict=True)
		)
		by_parent: dict = {}
		for row in rows:
			by_parent.setdefault((row.parenttype, row.parent), []).append(row)
		return by_parent
