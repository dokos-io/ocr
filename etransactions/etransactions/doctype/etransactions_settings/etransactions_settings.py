# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from erpnext.buying.doctype.buying_settings.buying_settings import BuyingSettings
from frappe import _
from frappe.model.document import Document


class eTransactionsSettings(Document):
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
		block_submission_on_blocking_findings: DF.Check
		block_submission_on_facturx_failure: DF.Check
		default_business_process_code: DF.Data | None
		default_etransaction_profile: DF.Link | None
		enable_receiving_einvoices: DF.Check
		enable_sending_einvoices: DF.Check
		generate_facturx_on_submit: DF.Check
		max_difference_amount: DF.Currency
		max_difference_percentage_on_net_total: DF.Percent
		mistral_api_key: DF.Password | None
		no_purchase_order: DF.Check
		ocr_service: DF.Literal["Amazon Textract", "Mistral OCR"]
		prefill_invoice_items: DF.Check
		reconcile_with_purchase_receipts: DF.Check
	# end: auto-generated types

	def validate(self):
		if self.reconcile_with_purchase_receipts and (
			self.max_difference_amount or self.max_difference_percentage_on_net_total
		):
			buying_settings: BuyingSettings = frappe.get_single("Buying Settings")  # type: ignore
			buying_settings.maintain_same_rate_action = "Warn"
			buying_settings.save()

			if self.max_difference_percentage_on_net_total:
				frappe.db.set_single_value(
					"Accounts Settings",
					"over_billing_allowance",
					self.max_difference_percentage_on_net_total + 0.01,
				)  # Hack to avoid rounding errors

	@frappe.whitelist()
	def test_connection(self, company: str):
		"""Test the active platform connection for the given company (any type)."""
		from etransactions.plateforme_agreee.session import (
			check_platform_health,
			get_platform_for_context,
		)

		platform_name = get_platform_for_context(company)
		if not platform_name:
			frappe.throw(
				_("No eTransactions Accredited Platform configured for company {0}.").format(company)
			)

		result = check_platform_health(platform_name)
		if result["status"] == "ok":
			frappe.msgprint(
				_("Connection to eTransactions Accredited Platform successful for {0}").format(company),
				alert=True,
				indicator="green",
			)
		else:
			frappe.throw(
				_("Connection failed for {0}: {1}").format(company, result["message"]),
				title=_("Connection failed"),
			)
