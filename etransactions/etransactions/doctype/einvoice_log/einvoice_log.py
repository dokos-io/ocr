# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now


class eInvoiceLog(Document):
	@staticmethod
	def clear_old_logs(days: int) -> None:
		table = frappe.qb.DocType("eInvoice Log")
		frappe.db.delete(table, filters=(table.creation < (Now() - Interval(days=days))))


def log_fetch(
	*,
	operation: str,
	status: str,
	company: str | None = None,
	einvoice: str | None = None,
	platform: str | None = None,
	flow_id: str | None = None,
	request: str | None = None,
	response: str | None = None,
) -> None:
	"""Record one platform fetch call (request + result), success or failure.

	Every call the reception pipeline makes to an accredited platform to list or
	download an invoice — not just the failures — so a support investigation can see
	exactly what was asked and what came back, instead of only the batch-level summary
	in eInvoicing Log. Auto-cleared by Log Settings (see default_log_clearing_doctypes
	in hooks.py) rather than a bespoke vacuum job.
	"""
	frappe.get_doc({
		"doctype": "eInvoice Log",
		"company": company,
		"einvoice": einvoice,
		"platform": platform,
		"operation": operation,
		"flow_id": flow_id,
		"status": status,
		"request": request,
		"response": response,
	}).insert(ignore_permissions=True)

	# A savepoint rollback further up the call stack (e.g. the download succeeded but
	# the subsequent parse/save didn't) must not erase the record of the call that did
	# succeed — except under test, where committing would break the rollback that
	# isolates each case.
	if not frappe.flags.in_test:
		frappe.db.commit()
