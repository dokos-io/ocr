# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import json

import frappe

from etransactions.etransactions_hub import api
from etransactions.tests.utils import eTransactionsTestSuite

IGNORE_TEST_RECORD_DEPENDENCIES = []


class TestAccountingHubApi(eTransactionsTestSuite):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.collaborator = "hub-collaborator@example.com"
		if not frappe.db.exists("User", cls.collaborator):
			user = frappe.new_doc("User")
			user.email = cls.collaborator
			user.first_name = "Hub Collaborator"
			user.insert(ignore_permissions=True)

		collaborator = frappe.get_doc("User", cls.collaborator)
		if not any(role.role == "Accounting Collaborator" for role in collaborator.roles):
			collaborator.append("roles", {"role": "Accounting Collaborator"})
			collaborator.save(ignore_permissions=True)

		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")

	def _delete_template(self, name):
		"""Remove a checklist template and any periods/tasks referencing it (suite commits)."""
		for period in frappe.get_all("Closing Period", filters={"checklist_template": name}, pluck="name"):
			for task in frappe.get_all("Closing Task", filters={"closing_period": period}, pluck="name"):
				frappe.delete_doc("Closing Task", task, force=True)
			frappe.delete_doc("Closing Period", period, force=True)
		if frappe.db.exists("Closing Checklist Template", name):
			frappe.delete_doc("Closing Checklist Template", name, force=True)

	def test_get_counts_shape(self):
		counts = api.get_counts()
		for key in ("waiting_on_me", "waiting_on_others", "overdue", "inbox_to_triage", "closing"):
			self.assertIn(key, counts)

	def test_create_request_with_assignment(self):
		request_name = api.create_request(
			subject="API created request",
			request_type="Missing Justificative",
			assign_to=self.collaborator,
			due_date=frappe.utils.add_days(frappe.utils.nowdate(), 3),
		)

		request = frappe.get_doc("Accounting Request", request_name)
		self.assertEqual(request.status, "Awaiting Response")
		self.assertIn(self.collaborator, frappe.parse_json(request.get("_assign") or "[]"))

	def test_create_request_from_inbox_item(self):
		item = frappe.new_doc("Accounting Inbox Item")
		item.sender = "supplier@example.com"
		item.subject = "Need clarification"
		item.insert()

		request_name = api.create_request(subject="From inbox", inbox_item=item.name)

		item.reload()
		self.assertEqual(item.created_request, request_name)
		self.assertEqual(item.status, "In Progress")

	def test_get_requests_scopes(self):
		request_name = api.create_request(subject="Scope test", assign_to=self.collaborator)

		all_requests = [request.name for request in api.get_requests(scope="all")]
		self.assertIn(request_name, all_requests)

		# in tests the session user is Administrator, who raised it but is not assigned
		raised = [request.name for request in api.get_requests(scope="raised")]
		self.assertIn(request_name, raised)

		mine = [request.name for request in api.get_requests(scope="mine")]
		self.assertNotIn(request_name, mine)

	def test_get_inbox_item_detail(self):
		item = frappe.new_doc("Accounting Inbox Item")
		item.sender = "supplier@example.com"
		item.subject = "Detail test"
		item.insert()

		detail = api.get_inbox_item(item.name)
		self.assertEqual(detail["item"]["name"], item.name)
		self.assertEqual(detail["communications"], [])
		self.assertEqual(detail["files"], [])

	def test_get_assignable_users_not_filtered_by_caller_permissions(self):
		"""Regression: the assignee list must not be filtered by the caller's User permissions."""
		baseline = api.get_assignable_users()
		self.assertTrue(baseline, "Expected the admin baseline to contain system users")
		self.assertIn("user_image", baseline[0])

		frappe.set_user(self.collaborator)
		restricted = api.get_assignable_users()

		# ignore_permissions means a low-privilege user sees the same full list.
		self.assertEqual(len(restricted), len(baseline))
		names = {user["name"] for user in restricted}
		self.assertNotIn("Administrator", names)
		self.assertNotIn("Guest", names)

	def test_get_inbox_filters(self):
		frappe.new_doc("Accounting Inbox Item", sender="alpha@example.com", subject="Alpha invoice").insert()
		frappe.new_doc("Accounting Inbox Item", title="Beta receipt", source="Manual Upload").insert()
		frappe.new_doc(
			"Accounting Inbox Item", sender="gamma@example.com", subject="Gamma note", status="Processed"
		).insert()

		processed = api.get_inbox(status="Processed")
		self.assertTrue(all(item["status"] == "Processed" for item in processed))

		by_source = api.get_inbox(source="Manual Upload")
		self.assertTrue(by_source)
		self.assertTrue(all(item["source"] == "Manual Upload" for item in by_source))

		by_search = api.get_inbox(search="Gamma")
		subjects = {item["subject"] for item in by_search}
		self.assertIn("Gamma note", subjects)
		self.assertNotIn("Alpha invoice", subjects)

	def test_save_checklist_template_create_and_update(self):
		self._delete_template("_Test Hub Template")

		name = api.save_checklist_template(
			json.dumps(
				{
					"template_name": "_Test Hub Template",
					"frequency": "Monthly",
					"items": [
						{"task_subject": "Reconcile bank", "day_offset": 0},
						{"task_subject": "File VAT", "day_offset": 5, "default_assignee": "Administrator"},
					],
				}
			)
		)

		template = frappe.get_doc("Closing Checklist Template", name)
		self.assertEqual(len(template.items), 2)
		self.assertEqual(template.items[1].default_assignee, "Administrator")

		api.save_checklist_template(
			json.dumps(
				{
					"name": name,
					"template_name": "_Test Hub Template",
					"frequency": "Quarterly",
					"items": [{"task_subject": "Reconcile bank accounts", "day_offset": 1}],
				}
			)
		)

		template.reload()
		self.assertEqual(template.frequency, "Quarterly")
		self.assertEqual(len(template.items), 1)
		self.assertEqual(template.items[0].task_subject, "Reconcile bank accounts")

		self._delete_template("_Test Hub Template")

	def test_update_and_delete_closing_period(self):
		from etransactions.etransactions_hub.doctype.closing_period.closing_period import (
			create_period_from_template,
		)

		template_name = "_Test Hub Period Template"
		self._delete_template(template_name)
		template = frappe.new_doc("Closing Checklist Template")
		template.template_name = template_name
		template.append("items", {"task_subject": "Task A", "day_offset": 0})
		template.insert()

		period_name = create_period_from_template(
			template_name, period_start="2026-08-01", period_end="2026-08-31"
		)

		api.update_closing_period(period_name, "2026-08-01", "2026-08-15")
		self.assertEqual(str(frappe.db.get_value("Closing Period", period_name, "period_end")), "2026-08-15")

		api.delete_closing_period(period_name)
		self.assertFalse(frappe.db.exists("Closing Period", period_name))
		self.assertFalse(frappe.db.exists("Closing Task", {"closing_period": period_name}))

		self._delete_template(template_name)

	def test_get_overview_shape(self):
		overview = api.get_overview()

		self.assertTrue(overview.get("company"))
		for key in ("waiting_on_me", "overdue", "inbox_to_triage"):
			self.assertIn(key, overview["collaboration"])
		self.assertIn("period", overview["close"])
		self.assertIn("missing_justificative_open", overview["data_quality"])

		# collaboration counters reuse the same helper as get_counts
		self.assertEqual(overview["collaboration"]["waiting_on_me"], api.get_counts()["waiting_on_me"])

		# aging buckets always sum to the reported total
		if "receivables" in overview:
			self.assertAlmostEqual(
				sum(overview["receivables"]["buckets"].values()), overview["receivables"]["total"]
			)

	def test_get_overview_aging_bucket(self):
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
		from frappe.utils import add_days, nowdate

		company = "_Test Company"
		before = api.get_overview(company)["receivables"]
		invoice = create_sales_invoice(
			company=company, posting_date=add_days(nowdate(), -45), rate=100, qty=1
		)
		after = api.get_overview(company)["receivables"]

		self.assertAlmostEqual(after["total"] - before["total"], invoice.outstanding_amount)
		# due 45 days ago → 31-60 bucket
		self.assertAlmostEqual(
			after["buckets"]["d31_60"] - before["buckets"]["d31_60"], invoice.outstanding_amount
		)

	def test_get_overview_permission_gating(self):
		frappe.set_user(self.collaborator)
		overview = api.get_overview()

		# A low-privilege collaborator still gets the call (no raise) and the collaboration block,
		# while sections they lack permission for are simply omitted.
		self.assertIn("collaboration", overview)
		self.assertTrue(overview.get("company"))
