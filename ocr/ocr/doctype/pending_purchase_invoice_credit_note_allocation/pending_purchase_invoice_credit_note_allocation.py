# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class PendingPurchaseInvoiceCreditNoteAllocation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allocated_amount: DF.Currency
		bill_no: DF.Data | None
		invoice_amount: DF.Currency
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		posting_date: DF.Date | None
		purchase_invoice: DF.Link
	# end: auto-generated types

	pass
