# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING

import frappe
from frappe.model.document import Document

if TYPE_CHECKING:
	from etransactions.etransactions_hub.doctype.closing_period.closing_period import ClosingPeriod


class ClosingTask(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		closing_period: DF.Link
		company: DF.Link | None
		description: DF.SmallText | None
		due_date: DF.Date | None
		route: DF.Data | None
		status: DF.Literal["Pending", "In Progress", "Blocked", "Done", "Not Applicable"]
		subject: DF.Data
	# end: auto-generated types

	def on_update(self):
		self._update_period_progress()

	def after_delete(self):
		self._update_period_progress()

	def _update_period_progress(self):
		if not frappe.db.exists("Closing Period", self.closing_period):
			return

		period: "ClosingPeriod" = frappe.get_doc("Closing Period", self.closing_period)  # type: ignore[assignment]
		period.update_progress()

	@frappe.whitelist()
	def create_request(self, request_type: str | None = None, subject: str | None = None):
		"""Create an Accounting Request linked to this closing task (e.g. when blocked)."""
		request = frappe.new_doc("Accounting Request")
		request.subject = subject or self.subject
		request.request_type = request_type or "Missing Justificative"
		request.company = self.company
		request.closing_task = self.name
		request.due_date = self.due_date
		request.insert()

		return request.name
