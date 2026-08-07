# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from etransactions.controllers.entity_resolver import (
	normalize_vendor_name,
	vendor_name_rejection_reason,
)


class eTransactionsSupplierNameAlias(Document):
	def validate(self):
		"""Keep the table a set of unambiguous vendor-name → supplier mappings.

		Supplier resolution trusts this table at "high" confidence, ahead of every
		name-similarity heuristic. A row that does not identify exactly one supplier
		therefore does not merely fail to help — it silently reassigns invoices.
		"""
		self.vendor_name = normalize_vendor_name(self.vendor_name)

		if reason := vendor_name_rejection_reason(self.vendor_name):
			frappe.throw(reason, title=_("Invalid vendor name"))

		claimants = set(
			frappe.get_all(
				"eTransactions Supplier Name Alias",
				filters={"vendor_name": self.vendor_name, "name": ("!=", self.name)},
				pluck="supplier",
			)
		)
		if claimants - {self.supplier}:
			frappe.throw(
				_("{0} is already mapped to {1}. A vendor name may only point at one supplier.").format(
					self.vendor_name, ", ".join(sorted(claimants))
				),
				title=_("Ambiguous vendor name"),
			)
