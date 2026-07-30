import frappe

from etransactions.etransactions.doctype.einvoice_event.einvoice_event import (
	refresh_einvoice_lifecycle_status,
)


def execute():
	"""Populate the new lifecycle_status projection on eInvoices that already have events.

	`lifecycle_status` / `lifecycle_status_datetime` are a denormalised view of the
	eInvoice Event history, refreshed from now on whenever an event is recorded. Existing
	invoices carry a history that predates the fields, so compute it once here.
	"""
	if not frappe.db.table_exists("eInvoice Event"):
		return

	einvoices = frappe.get_all(
		"eInvoice Event",
		filters={"einvoice": ("is", "set")},
		distinct=True,
		pluck="einvoice",
	)

	for einvoice in einvoices:
		refresh_einvoice_lifecycle_status(einvoice)
