# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

class OCRLineItemsMapping(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		expense_row: DF.SmallText | None
		item: DF.SmallText | None
		item_code: DF.Link | None
		other: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		price: DF.Float
		product_code: DF.SmallText | None
		quantity: DF.Float
		unit_price: DF.Float
	# end: auto-generated types

	pass
