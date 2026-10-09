# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from etransactions.controllers.entity_resolver import (
	MIN_COMPANY_ALIAS_LENGTH,
	company_name_key,
	normalize_vendor_name,
)


class eTransactionsCompanyNameAlias(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		company: DF.Link
		receiver_name: DF.Data
	# end: auto-generated types

	def validate(self):
		"""A receiver name may only point at one company: the buyer match trusts it as is."""
		self.receiver_name = normalize_vendor_name(self.receiver_name)

		key = company_name_key(self.receiver_name)
		if len(key) < MIN_COMPANY_ALIAS_LENGTH:
			frappe.throw(_("{0} is too generic to identify a company.").format(self.receiver_name))

		claimants = {
			alias.company
			for alias in frappe.get_all(
				"eTransactions Company Name Alias",
				filters={"name": ("!=", self.name)},
				fields=["receiver_name", "company"],
			)
			if company_name_key(alias.receiver_name) == key
		}
		if claimants - {self.company}:
			frappe.throw(
				_("{0} is already mapped to {1}. A receiver name may only point at one company.").format(
					self.receiver_name, ", ".join(sorted(claimants))
				),
				title=_("Ambiguous receiver name"),
			)
