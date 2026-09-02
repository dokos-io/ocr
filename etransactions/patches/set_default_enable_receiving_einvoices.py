import frappe


def execute():
	"""Preserve existing behaviour on upgrade.

	Before this patch, `poll_incoming_flows` ignored the module switch entirely and
	received invoices for any active accredited platform. The new
	`enable_receiving_einvoices` field's JSON default (1) does not backfill onto the
	existing eTransactions Settings singleton, so turn it on explicitly here to keep
	receiving working for sites that already rely on it.
	"""
	if frappe.get_single_value("eTransactions Settings", "enable_receiving_einvoices"):
		return

	frappe.db.set_single_value("eTransactions Settings", "enable_receiving_einvoices", 1)
