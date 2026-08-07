# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document


def normalize_supplier_item_code(label: str | None) -> str:
	"""Reduce a supplier's line label to a stable lookup key.

	Suppliers rarely repeat a line verbatim: amounts, periods and currencies drift from one
	invoice to the next ("AWS Service Charges EUR 3.60" then "... EUR 4.12"). Case, spacing
	and trailing punctuation drift too. Keying on the raw string would learn a mapping that
	never matches again.
	"""
	label = re.sub(r"\s+", " ", label or "").strip().lower()
	# Amounts and standalone numbers are the volatile part of a line label, not its identity.
	label = re.sub(r"[\d]+([.,][\d]+)*\s*(%|€|\$|eur|usd|gbp)?", " ", label)
	label = re.sub(r"[^\w\s]", " ", label, flags=re.UNICODE)

	return re.sub(r"\s+", " ", label).strip()[:140]


def get_supplier_item_alias(supplier: str | None, label: str | None) -> frappe._dict | None:
	"""The Item this supplier's line label maps to, or None if it is not yet known."""
	key = normalize_supplier_item_code(label)
	if not supplier or not key:
		return None

	aliases = frappe.get_all(
		"eTransactions Supplier Item Alias",
		filters={"supplier": supplier, "supplier_item_code": key},
		fields=["item_code", "expense_account", "cost_center", "item_tax_template"],
		limit=1,
	)

	return aliases[0] if aliases else None


class eTransactionsSupplierItemAlias(Document):
	def validate(self):
		"""Keep one Item per (supplier, line label).

		Prefill reads this table without asking, so an ambiguous key would put an arbitrary
		Item — and expense account — on an invoice the user is about to submit.
		"""
		self.supplier_item_code = normalize_supplier_item_code(self.supplier_item_code)
		if not self.supplier_item_code:
			frappe.throw(
				_("The supplier item code carries no text to match on."),
				title=_("Invalid supplier item code"),
			)

		duplicate = frappe.db.exists(
			"eTransactions Supplier Item Alias",
			{
				"supplier": self.supplier,
				"supplier_item_code": self.supplier_item_code,
				"name": ("!=", self.name),
			},
		)
		if duplicate:
			frappe.throw(
				_("{0} is already mapped for this supplier.").format(self.supplier_item_code),
				title=_("Duplicate supplier item code"),
			)
