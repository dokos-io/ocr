# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.desk.form.assign_to import add as add_assignment
from frappe.model.document import Document
from frappe.utils import add_days, flt, formatdate, get_first_day, get_last_day, getdate, nowdate

if TYPE_CHECKING:
	from etransactions.accounting_hub.doctype.closing_checklist_template.closing_checklist_template import (
		ClosingChecklistTemplate,
	)


class ClosingPeriod(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		checklist_template: DF.Link
		company: DF.Link | None
		period_end: DF.Date
		period_start: DF.Date
		progress: DF.Percent
		status: DF.Literal["Open", "In Progress", "Completed"]
		title: DF.Data | None
	# end: auto-generated types

	def validate(self):
		self._validate_dates()
		self._validate_duplicate()
		self._set_title()

	def _validate_dates(self):
		if getdate(self.period_start) > getdate(self.period_end):
			frappe.throw(_("Period start date cannot be after period end date"))

	def _validate_duplicate(self):
		duplicate = frappe.db.exists(
			"Closing Period",
			{
				"checklist_template": self.checklist_template,
				"period_start": self.period_start,
				"period_end": self.period_end,
				"name": ("!=", self.name),
			},
		)
		if duplicate:
			frappe.throw(
				_("Closing Period {0} already exists for this template and period").format(duplicate)
			)

	def _set_title(self):
		self.title = "{0} — {1}".format(
			self.checklist_template, formatdate(self.period_end, "MMMM yyyy")
		)

	def create_tasks_from_template(self):
		"""Create one Closing Task per template item and assign it to the default assignee."""
		template: "ClosingChecklistTemplate" = frappe.get_doc(
			"Closing Checklist Template", self.checklist_template
		)  # type: ignore[assignment]

		for item in template.items:
			task = frappe.new_doc("Closing Task")
			task.subject = item.task_subject
			task.closing_period = self.name
			task.description = item.description
			task.route = item.route
			task.due_date = add_days(self.period_end, item.day_offset)
			task.insert()

			if item.default_assignee:
				add_assignment(
					{
						"assign_to": [item.default_assignee],
						"doctype": task.doctype,
						"name": task.name,
						"description": task.subject,
						"date": task.due_date,
					},
					ignore_permissions=True,
				)

	def update_progress(self):
		"""Recompute progress and status from the period's tasks. Called by Closing Task hooks."""
		statuses = frappe.get_all(
			"Closing Task", filters={"closing_period": self.name}, pluck="status"
		)

		relevant = [status for status in statuses if status != "Not Applicable"]
		done = [status for status in relevant if status == "Done"]

		progress = flt(len(done)) / len(relevant) * 100 if relevant else 0

		if statuses and not [status for status in relevant if status != "Done"]:
			status = "Completed"
		elif done or [status for status in statuses if status not in ("Pending",)]:
			status = "In Progress"
		else:
			status = "Open"

		self.db_set("progress", progress)
		self.db_set("status", status)


@frappe.whitelist()
def create_period_from_template(
	checklist_template: str, period_start: str | None = None, period_end: str | None = None
) -> str:
	"""Create a Closing Period with its tasks. Defaults to the current month."""
	template_company = frappe.db.get_value(
		"Closing Checklist Template", checklist_template, "company"
	)

	period: ClosingPeriod = frappe.new_doc("Closing Period")  # type: ignore[assignment]
	period.checklist_template = checklist_template
	period.company = template_company
	period.period_start = period_start or get_first_day(nowdate())
	period.period_end = period_end or get_last_day(nowdate())
	period.insert()

	period.create_tasks_from_template()

	return period.name
