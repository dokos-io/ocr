# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

class OCRHeaderMapping(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		field: DF.Data | None
		field_value: DF.SmallText | None
		key: DF.Data
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		value: DF.SmallText | None
	# end: auto-generated types

	pass
