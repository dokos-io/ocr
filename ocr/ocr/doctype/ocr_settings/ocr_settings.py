# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

class OCRSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		auto_create_purchase_orders: DF.Check
		auto_submit_purchase_invoices: DF.Check
		aws_textract_key: DF.Data | None
		aws_textract_secret: DF.Password | None
		block_if_grand_total_exceeds_pending_pi: DF.Check
		block_if_net_total_exceeds_pending_pi: DF.Check
		no_purchase_order: DF.Check
	# end: auto-generated types

	pass
