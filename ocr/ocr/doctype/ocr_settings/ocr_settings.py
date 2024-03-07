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

		aws_textract_key: DF.Data | None
		aws_textract_secret: DF.Password | None
		generic_item: DF.Link | None
		pi_creation_mode: DF.Literal["Get items from the OCR analysis", "Get items from purchase orders recognized by the OCR", "Get items from any open purchase order linked to the recognized supplier", "Consolidate all rows in a single invoicing line"]
		selected_ocr_service: DF.Literal["AWS Textract", "Taggun"]
		taggun_api_key: DF.Password | None
	# end: auto-generated types

	pass
