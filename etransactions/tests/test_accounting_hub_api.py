# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe

from etransactions.accounting_hub import api
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
		frappe.db.commit()

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
