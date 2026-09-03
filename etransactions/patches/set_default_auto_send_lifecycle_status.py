import frappe


def execute():
	"""Preserve existing behaviour on upgrade.

	The `auto_send_in_hand`/`auto_send_approved`/`auto_send_payment` fields' JSON
	default (1) does not backfill onto an eTransactions Settings singleton that
	already existed before these fields were added, so sites provisioned earlier
	silently never report lifecycle status back to the accredited platform. Turn
	them on explicitly here to match the intended default.
	"""
	for field in ("auto_send_in_hand", "auto_send_approved", "auto_send_payment"):
		if frappe.get_single_value("eTransactions Settings", field):
			continue
		frappe.db.set_single_value("eTransactions Settings", field, 1)
