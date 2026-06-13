# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, nowdate

from erpnext.accounts.doctype.bank_transaction.test_bank_transaction import (
	create_bank_account,
	create_gl_account,
)

from etransactions.etransactions_hub.doctype.accounting_request.accounting_request import (
	notify_overdue_requests,
)
from etransactions.tests.utils import eTransactionsTestSuite, minimal_pdf_content

IGNORE_TEST_RECORD_DEPENDENCIES = []


class TestAccountingRequest(eTransactionsTestSuite):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		gl_account = "_Test Hub Bank - _TC"
		if not frappe.db.exists("Account", gl_account):
			gl_account = create_gl_account("_Test Hub Bank")
		cls.bank_account = create_bank_account(
			bank_name="Test Hub Bank", gl_account=gl_account, bank_account_name="Hub Checking Account"
		)
		cls.bank_transaction = frappe.new_doc("Bank Transaction")
		cls.bank_transaction.update(
			{
				"date": nowdate(),
				"description": "CB AWS",
				"withdrawal": 142.30,
				"currency": "INR",
				"bank_account": cls.bank_account,
				"company": "_Test Company",
				"party_type": "Supplier",
			}
		)
		cls.bank_transaction.insert()

		cls.collaborator = "hub-collaborator@example.com"
		if not frappe.db.exists("User", cls.collaborator):
			user = frappe.new_doc("User")
			user.email = cls.collaborator
			user.first_name = "Hub Collaborator"
			user.insert(ignore_permissions=True)

		frappe.db.commit()

	def make_request(self, **kwargs) -> "frappe.model.document.Document":
		request = frappe.new_doc("Accounting Request")
		request.subject = kwargs.pop("subject", "Test request")
		request.update(kwargs)
		request.insert()
		return request

	def make_communication(self, request, sent_or_received="Received", with_attachment=False):
		communication = frappe.new_doc("Communication")
		communication.update(
			{
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": sent_or_received,
				"subject": f"Re: {request.subject}",
				"content": "Here is the document",
				"sender": "owner@example.com",
				"reference_doctype": request.doctype,
				"reference_name": request.name,
			}
		)
		communication.flags.skip_add_signature = True
		communication.insert(ignore_permissions=True)

		if with_attachment:
			self.attach_file(communication.doctype, communication.name)

		return communication

	def attach_file(self, doctype: str, name: str) -> str:
		file = frappe.new_doc("File")
		file.update(
			{
				"file_name": f"justificative-{frappe.generate_hash(length=6)}.pdf",
				"attached_to_doctype": doctype,
				"attached_to_name": name,
				"is_private": 1,
				"content": minimal_pdf_content(),
			}
		)
		file.insert()
		return file.name

	def test_defaults_without_reference(self):
		request = self.make_request()
		self.assertEqual(request.status, "Open")
		self.assertEqual(request.raised_by, frappe.session.user)

	def test_context_from_bank_transaction(self):
		request = self.make_request(
			reference_doctype="Bank Transaction",
			reference_name=self.bank_transaction.name,
		)
		self.assertEqual(request.context_amount, 142.30)
		self.assertEqual(str(request.context_date), str(self.bank_transaction.date))
		self.assertEqual(request.company, "_Test Company")

	def test_reference_must_exist(self):
		self.assertRaises(
			frappe.ValidationError,
			self.make_request,
			reference_doctype="Bank Transaction",
			reference_name="DOES-NOT-EXIST",
		)

	def test_inbound_communication_flips_awaiting_status(self):
		request = self.make_request(status="Awaiting Response")
		self.make_communication(request, sent_or_received="Received")
		self.assertEqual(
			frappe.db.get_value("Accounting Request", request.name, "status"), "Response Received"
		)

	def test_sent_communication_does_not_flip_status(self):
		request = self.make_request(status="Awaiting Response")
		self.make_communication(request, sent_or_received="Sent")
		self.assertEqual(
			frappe.db.get_value("Accounting Request", request.name, "status"), "Awaiting Response"
		)

	def test_communication_does_not_flip_other_statuses(self):
		request = self.make_request(status="Resolved")
		self.make_communication(request, sent_or_received="Received")
		self.assertEqual(frappe.db.get_value("Accounting Request", request.name, "status"), "Resolved")

	def test_resolve(self):
		request = self.make_request(status="Response Received")
		request.resolve()
		self.assertEqual(request.status, "Resolved")
		self.assertEqual(request.resolved_by, frappe.session.user)
		self.assertTrue(request.resolved_on)

		self.assertRaises(frappe.ValidationError, request.resolve)

	def test_overdue_notification_for_assignee(self):
		from frappe.desk.form.assign_to import add as add_assignment

		request = self.make_request(status="Awaiting Response", due_date=add_days(nowdate(), -2))
		add_assignment(
			{
				"assign_to": [self.collaborator],
				"doctype": request.doctype,
				"name": request.name,
				"description": request.subject,
			},
			ignore_permissions=True,
		)

		notifications_before = frappe.db.count(
			"Notification Log", {"document_name": request.name, "type": "Alert"}
		)
		notify_overdue_requests()
		notifications_after = frappe.db.count(
			"Notification Log", {"document_name": request.name, "type": "Alert"}
		)
		self.assertEqual(notifications_after, notifications_before + 1)

	def test_attach_to_reference_requires_reference(self):
		request = self.make_request()
		self.assertRaises(frappe.ValidationError, request.attach_to_reference)

	def test_attach_to_reference_requires_file(self):
		request = self.make_request(
			reference_doctype="Bank Transaction",
			reference_name=self.bank_transaction.name,
		)
		self.assertRaises(frappe.ValidationError, request.attach_to_reference)

	def test_attach_to_reference_copies_communication_files(self):
		request = self.make_request(
			reference_doctype="Bank Transaction",
			reference_name=self.bank_transaction.name,
			status="Awaiting Response",
		)
		self.make_communication(request, sent_or_received="Received", with_attachment=True)

		files_before = frappe.db.count(
			"File",
			{"attached_to_doctype": "Bank Transaction", "attached_to_name": self.bank_transaction.name},
		)
		request.attach_to_reference()
		files_after = frappe.db.count(
			"File",
			{"attached_to_doctype": "Bank Transaction", "attached_to_name": self.bank_transaction.name},
		)
		self.assertEqual(files_after, files_before + 1)

		# the source file stays on the communication (audit trail)
		self.assertTrue(
			frappe.db.exists(
				"File",
				{"attached_to_doctype": "Communication"},
			)
		)
