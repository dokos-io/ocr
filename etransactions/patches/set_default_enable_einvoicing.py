import frappe


def execute():
	"""Preserve existing behaviour on upgrade.

	The new `enable_einvoicing` switch is off by default (pure opt-in for new
	sites). On sites already using e-invoicing — an active accredited platform
	or a default eTransaction Profile — turn it on so their fields and actions
	keep showing.
	"""
	if frappe.get_single_value("eTransactions Settings", "enable_einvoicing"):
		return

	has_active_platform = frappe.db.exists("eTransactions Accredited Platform", {"is_active": 1})
	has_default_profile = frappe.get_single_value(
		"eTransactions Settings", "default_etransaction_profile"
	)

	if has_active_platform or has_default_profile:
		frappe.db.set_single_value("eTransactions Settings", "enable_einvoicing", 1)
