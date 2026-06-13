# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ClosingChecklistTemplateItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		day_offset: DF.Int
		default_assignee: DF.Link | None
		description: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		route: DF.Data | None
		task_subject: DF.Data
	# end: auto-generated types

	pass
