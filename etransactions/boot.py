import frappe

from etransactions.features import get_enabled_features


def boot_session(bootinfo):
	"""Expose the e-invoicing activation flag to the client.

	Drives both the visibility of the eTransactions custom fields
	(depends_on: eval:frappe.boot.einvoicing_enabled) and the eInvoicing
	button guards in the per-form client scripts.
	"""
	bootinfo.einvoicing_enabled = int(
		frappe.db.get_single_value("eTransactions Settings", "enable_einvoicing") or 0
	)
	# Optional features (Peppol, public sector, profile choice, advanced routing):
	# each reveals its own fields (depends_on: frappe.boot.einvoicing_features.<key>).
	bootinfo.einvoicing_features = get_enabled_features()

	# SIRENE autofill (see customer.js / supplier.js) is redundant with ERPNext's Pappers
	# integration; expose whether Pappers is enabled so those scripts can hide the SIRENE
	# button when Pappers already covers the same French company lookup.
	bootinfo.pappers_enabled = 0
	try:
		from erpnext.regional.france.pappers.api import pappers_enabled

		bootinfo.pappers_enabled = int(pappers_enabled())
	except Exception:
		pass
