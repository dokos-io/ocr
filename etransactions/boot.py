import frappe


def boot_session(bootinfo):
	"""Expose the e-invoicing activation flag to the client.

	Drives both the visibility of the eTransactions custom fields
	(depends_on: eval:frappe.boot.einvoicing_enabled) and the eInvoicing
	button guards in the per-form client scripts.
	"""
	bootinfo.einvoicing_enabled = int(
		frappe.db.get_single_value("eTransactions Settings", "enable_einvoicing") or 0
	)
