# Copyright (c) 2024, Dokos SAS and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class PendingPurchaseInvoiceItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Float
		cost_center: DF.Link | None
		expense_account: DF.Link | None
		item_code: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		project: DF.Link | None
		qty: DF.Float
		rate: DF.Float
		reference_docname: DF.DynamicLink | None
		reference_doctype: DF.Link | None
		row: DF.Data | None
		supplier_description: DF.SmallText | None
		supplier_item_code: DF.SmallText | None
	# end: auto-generated types
	pass
