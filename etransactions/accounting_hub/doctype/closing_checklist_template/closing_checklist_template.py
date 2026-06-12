# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ClosingChecklistTemplate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from etransactions.accounting_hub.doctype.closing_checklist_template_item.closing_checklist_template_item import (
			ClosingChecklistTemplateItem,
		)

		company: DF.Link | None
		frequency: DF.Literal["Monthly", "Quarterly", "Yearly"]
		items: DF.Table[ClosingChecklistTemplateItem]
		template_name: DF.Data
	# end: auto-generated types

	pass
