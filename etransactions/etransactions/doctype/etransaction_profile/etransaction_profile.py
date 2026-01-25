# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

from frappe.modules.utils import export_module_json

class eTransactionProfile(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		identifier_value: DF.Data
		profile: DF.Data
	# end: auto-generated types

	def on_update(self):
		export_module_json(self, True, "eTransactions")
