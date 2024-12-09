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

		cost_center: DF.Link | None
		item: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		price: DF.Float
		project: DF.Link | None
		quantity: DF.Float
		supplier_description: DF.SmallText | None
		supplier_item_code: DF.SmallText | None
		unit_price: DF.Float
	# end: auto-generated types
	pass
