# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, getdate

from etransactions.accounting_hub.doctype.closing_period.closing_period import (
	create_period_from_template,
)
from etransactions.tests.utils import eTransactionsTestSuite

IGNORE_TEST_RECORD_DEPENDENCIES = []


class TestClosingPeriod(eTransactionsTestSuite):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Closing Checklist Template", "_Test Monthly Closing"):
			template = frappe.new_doc("Closing Checklist Template")
			template.template_name = "_Test Monthly Closing"
			template.frequency = "Monthly"
			template.append(
				"items",
				{"task_subject": "Bank reconciliation done", "day_offset": 0, "default_assignee": "Administrator"},
			)
			template.append("items", {"task_subject": "VAT return prepared", "day_offset": 3})
			template.append("items", {"task_subject": "Inbox cleared", "day_offset": 5})
			template.insert()
			frappe.db.commit()

	def make_period(self, period_start="2026-05-01", period_end="2026-05-31") -> str:
		return create_period_from_template(
			"_Test Monthly Closing", period_start=period_start, period_end=period_end
		)

	def get_tasks(self, period_name: str) -> list[dict]:
		return frappe.get_all(
			"Closing Task",
			filters={"closing_period": period_name},
			fields=["name", "subject", "status", "due_date", "_assign"],
			order_by="due_date asc",
		)

	def test_create_period_from_template(self):
		period_name = self.make_period()
		period = frappe.get_doc("Closing Period", period_name)

		self.assertEqual(period.status, "Open")
		self.assertIn("_Test Monthly Closing", period.title)

		tasks = self.get_tasks(period_name)
		self.assertEqual(len(tasks), 3)
		self.assertEqual(tasks[0].due_date, getdate("2026-05-31"))
		self.assertEqual(tasks[2].due_date, getdate(add_days("2026-05-31", 5)))

		assigned_task = [task for task in tasks if task.subject == "Bank reconciliation done"][0]
		self.assertIn("Administrator", frappe.parse_json(assigned_task._assign or "[]"))

	def test_duplicate_period_is_rejected(self):
		self.make_period(period_start="2026-04-01", period_end="2026-04-30")
		self.assertRaises(
			frappe.ValidationError,
			self.make_period,
			period_start="2026-04-01",
			period_end="2026-04-30",
		)

	def test_period_dates_are_validated(self):
		self.assertRaises(
			frappe.ValidationError,
			self.make_period,
			period_start="2026-03-31",
			period_end="2026-03-01",
		)

	def test_progress_and_status_rollup(self):
		period_name = self.make_period(period_start="2026-06-01", period_end="2026-06-30")
		tasks = self.get_tasks(period_name)

		def period_value(field: str):
			return frappe.db.get_value("Closing Period", period_name, field)

		first_task = frappe.get_doc("Closing Task", tasks[0].name)
		first_task.status = "Not Applicable"
		first_task.save()
		self.assertEqual(period_value("progress"), 0)

		second_task = frappe.get_doc("Closing Task", tasks[1].name)
		second_task.status = "Done"
		second_task.save()
		self.assertEqual(period_value("progress"), 50)
		self.assertEqual(period_value("status"), "In Progress")

		third_task = frappe.get_doc("Closing Task", tasks[2].name)
		third_task.status = "Done"
		third_task.save()
		self.assertEqual(period_value("progress"), 100)
		self.assertEqual(period_value("status"), "Completed")

	def test_create_request_from_blocked_task(self):
		period_name = self.make_period(period_start="2026-07-01", period_end="2026-07-31")
		task_name = self.get_tasks(period_name)[0].name

		task = frappe.get_doc("Closing Task", task_name)
		task.status = "Blocked"
		task.save()

		request_name = task.create_request(subject="Missing 3 justificatives")
		request = frappe.get_doc("Accounting Request", request_name)
		self.assertEqual(request.closing_task, task.name)
		self.assertEqual(request.request_type, "Missing Justificative")
		self.assertEqual(str(request.due_date), str(task.due_date))
