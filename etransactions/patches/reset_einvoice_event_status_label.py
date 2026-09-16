import frappe

from etransactions.plateforme_agreee import lifecycle_status


def execute():
	"""Store the untranslated lifecycle label on eInvoice Events.

	The label used to be translated on insert, freezing it in the language of whoever
	created the event (usually the scheduler). It is now kept in English — the
	translation key — and translated on display.
	"""
	if not frappe.db.table_exists("eInvoice Event"):
		return

	for status in lifecycle_status.LABELS:
		frappe.db.set_value(
			"eInvoice Event",
			{"status": status},
			"status_label",
			lifecycle_status.source_label(status),
			update_modified=False,
		)
