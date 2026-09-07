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

	Nothing here commits: the entry is written into the caller's transaction and
	committed with it. A caller that logs from inside a savepoint region must buffer
	through :class:`FetchLogBuffer` instead — see the note there.
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


class FetchLogBuffer:
	"""Collects platform-call audit entries to be written once the caller is done.

	Writing them as they happen would be simpler, but the callers that need this all
	run inside a savepoint region, and the entries have to outlive a rollback to that
	savepoint — the record of a download that did succeed must not be erased because
	the parse that followed failed. Committing on the spot to achieve that is exactly
	what must not happen: a COMMIT ends the transaction and takes every savepoint with
	it, so the ``ROLLBACK TO SAVEPOINT`` / ``RELEASE SAVEPOINT`` that follows fails
	with MariaDB error 1305 and the caller's own error handling never runs.

	So the entries are held here and flushed after the region closes, where they land
	in the caller's transaction and are committed with it.

	The identifying context is fixed for the whole buffer; only what varies per call
	is passed to :meth:`add`.
	"""

	def __init__(
		self,
		*,
		company: str | None = None,
		einvoice: str | None = None,
		platform: str | None = None,
		flow_id: str | None = None,
	):
		self.context = {
			"company": company,
			"einvoice": einvoice,
			"platform": platform,
			"flow_id": flow_id,
		}
		self.entries: list[dict] = []

	def add(
		self, *, operation: str, status: str, request: str | None = None, response: str | None = None
	) -> None:
		self.entries.append({
			"operation": operation,
			"status": status,
			"request": request,
			"response": response,
		})

	def flush(self) -> None:
		"""Write every buffered entry, then empty the buffer so a retry starts clean."""
		entries, self.entries = self.entries, []
		for entry in entries:
			log_fetch(**self.context, **entry)
