# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class eTransactionsAccreditedPlatform(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_base_url: DF.Data | None
		auto_send_on_submit: DF.Check
		client_id: DF.Password | None
		client_secret: DF.Password | None
		company: DF.Link
		description: DF.Text | None
		directory_refresh_days: DF.Int
		is_active: DF.Check
		platform_code: DF.Data
		platform_name: DF.Data
		platform_type: DF.Literal["Custom", "SuperPDP", "Esalink"]
		transaction_type: DF.Literal["Both", "Sales", "Purchases"]
	# end: auto-generated types

	def validate(self):
		if self.platform_type == "SuperPDP":
			self.platform_code = "superpdp"
		elif self.platform_type == "Esalink":
			self.platform_code = "esalink"


@frappe.whitelist()
def get_platforms(company=None, transaction_type=None):
	"""Get all eTransactions Accredited Platforms for the HTML component."""
	filters = {}
	if company:
		filters["company"] = company
	if transaction_type:
		filters["transaction_type"] = ["in", [transaction_type.capitalize(), "Both"]]

	platforms = frappe.get_all(
		"eTransactions Accredited Platform",
		fields=["name", "platform_name", "platform_type", "platform_code", "company", "transaction_type", "is_active", "api_base_url", "description", "auto_send_on_submit", "directory_refresh_days"],
		filters=filters,
		order_by="company, platform_name"
	)
	return platforms


@frappe.whitelist()
def save_platform(platform_data, existing_name=None):
	"""Save an eTransactions Accredited Platform (create or update)."""
	if isinstance(platform_data, str):
		platform_data = json.loads(platform_data)

	if existing_name:
		doc = frappe.get_doc("eTransactions Accredited Platform", existing_name)
	else:
		doc = frappe.new_doc("eTransactions Accredited Platform")

	for key, value in platform_data.items():
		if hasattr(doc, key):
			setattr(doc, key, value)

	doc.save()
	return doc.name


@frappe.whitelist()
def delete_platform(platform_name):
	"""Delete an eTransactions Accredited Platform."""
	settings = frappe.get_single("eTransactions Settings")
	if platform_name in (settings.default_sales_platform, settings.default_purchases_platform):
		frappe.throw(
			_("Cannot delete platform '{0}' because it is set as a default platform in eTransactions Settings.").format(platform_name)
		)

	used_in_customer = frappe.db.exists("Customer", {"accredited_platform_override": platform_name})
	used_in_customer_group = frappe.db.exists("Customer Group", {"accredited_platform_override": platform_name})

	if used_in_customer or used_in_customer_group:
		frappe.throw(
			_("Cannot delete platform '{0}' because it is used in Customer or Customer Group overrides.").format(platform_name)
		)

	frappe.delete_doc("eTransactions Accredited Platform", platform_name)
	return True


@frappe.whitelist()
def toggle_active(platform_name, is_active):
	"""Toggle the active status of an eTransactions Accredited Platform."""
	frappe.db.set_value("eTransactions Accredited Platform", platform_name, "is_active", is_active)
	return True
