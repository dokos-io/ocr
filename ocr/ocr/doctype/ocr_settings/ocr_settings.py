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

		auto_submit_purchase_invoices: DF.Check
		aws_textract_key: DF.Data | None
		aws_textract_secret: DF.Password | None
		block_if_grand_total_exceeds_pending_pi: DF.Check
		block_if_net_total_exceeds_pending_pi: DF.Check
		max_difference_amount: DF.Currency
		max_difference_percentage_on_net_total: DF.Percent
		mistral_api_key: DF.Password | None
		no_purchase_order: DF.Check
		ocr_service: DF.Literal["Amazon Textract", "Mistral OCR"]
		reconcile_with_purchase_receipts: DF.Check
	# end: auto-generated types

	pass
