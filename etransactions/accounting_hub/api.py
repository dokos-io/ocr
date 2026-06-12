# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe.translate import get_all_translations
from frappe.utils import nowdate

OPEN_REQUEST_STATUSES = ("Open", "Awaiting Response", "Response Received")


@frappe.whitelist(allow_guest=True)
def get_translations() -> dict:
	if frappe.session.user != "Guest":
		language = frappe.db.get_value("User", frappe.session.user, "language")
	else:
		language = frappe.db.get_single_value("System Settings", "language")

	return get_all_translations(language)


@frappe.whitelist()
def get_counts() -> dict:
	"""Aggregated counters for the Accounting Hub home screen."""
	frappe.has_permission("Accounting Request", throw=True)

	user = frappe.session.user

	counts = {
		"waiting_on_me": frappe.db.count(
			"Accounting Request",
			{"status": ("in", OPEN_REQUEST_STATUSES), "_assign": ("like", f'%"{user}"%')},
		),
		"waiting_on_others": frappe.db.count(
			"Accounting Request",
			{
				"status": ("in", OPEN_REQUEST_STATUSES),
				"raised_by": user,
				"_assign": ("not like", f'%"{user}"%'),
			},
		),
		"overdue": frappe.db.count(
			"Accounting Request",
			{"status": ("in", OPEN_REQUEST_STATUSES), "due_date": ("<", nowdate())},
		),
		"inbox_to_triage": 0,
		"closing": None,
	}

	if frappe.has_permission("Accounting Inbox Item"):
		counts["inbox_to_triage"] = frappe.db.count(
			"Accounting Inbox Item", {"status": ("in", ("To Triage", "In Progress"))}
		)

	if frappe.has_permission("Closing Period"):
		current_period = frappe.get_all(
			"Closing Period",
			filters={"status": ("!=", "Completed")},
			fields=["name", "title", "progress", "status", "period_end"],
			order_by="period_end desc",
			limit=1,
		)
		counts["closing"] = current_period[0] if current_period else None

	return counts


@frappe.whitelist()
def get_inbox(status: str | None = None) -> list[dict]:
	"""Inbox items for the triage view."""
	filters = {}
	if status:
		filters["status"] = status

	return frappe.get_list(
		"Accounting Inbox Item",
		filters=filters,
		fields=[
			"name",
			"title",
			"sender",
			"subject",
			"status",
			"source",
			"company",
			"created_request",
			"created_invoices_basket",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=100,
	)


@frappe.whitelist()
def get_inbox_item(name: str) -> dict:
	"""Detail of one inbox item: document, email thread and attached files."""
	item = frappe.get_doc("Accounting Inbox Item", name)
	item.check_permission("read")

	communications = frappe.get_all(
		"Communication",
		filters={"reference_doctype": item.doctype, "reference_name": item.name},
		fields=["name", "subject", "sender", "content", "creation"],
		order_by="creation asc",
	)

	files = []
	for source_doctype, source_name in [(item.doctype, item.name)] + [
		("Communication", communication.name) for communication in communications
	]:
		files.extend(
			frappe.get_all(
				"File",
				filters={"attached_to_doctype": source_doctype, "attached_to_name": source_name},
				fields=["name", "file_name", "file_url", "file_type"],
			)
		)

	return {"item": item.as_dict(), "communications": communications, "files": files}


@frappe.whitelist()
def get_assignable_users() -> list[dict]:
	"""Active desk users that a request can be assigned to."""
	frappe.has_permission("Accounting Request", throw=True)

	return frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User", "name": ("not in", ("Administrator", "Guest"))},
		fields=["name", "full_name"],
		order_by="full_name asc",
	)


@frappe.whitelist()
def create_request(
	subject: str,
	request_type: str = "Question",
	description: str | None = None,
	due_date: str | None = None,
	assign_to: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	inbox_item: str | None = None,
) -> str:
	"""Create an Accounting Request from the SPA, optionally assigning it."""
	from frappe.desk.form.assign_to import add as add_assignment

	request = frappe.new_doc("Accounting Request")
	request.subject = subject
	request.request_type = request_type
	request.description = description
	request.due_date = due_date
	request.reference_doctype = reference_doctype
	request.reference_name = reference_name
	request.inbox_item = inbox_item
	request.status = "Awaiting Response" if assign_to else "Open"
	request.insert()

	if assign_to:
		add_assignment(
			{
				"assign_to": [assign_to],
				"doctype": request.doctype,
				"name": request.name,
				"description": subject,
				"date": due_date,
			}
		)

	if inbox_item:
		item = frappe.get_doc("Accounting Inbox Item", inbox_item)
		item.check_permission("write")
		item.db_set("created_request", request.name)
		if item.status == "To Triage":
			item.db_set("status", "In Progress")

	return request.name


@frappe.whitelist()
def get_requests(scope: str = "mine") -> list[dict]:
	"""Requests for the board view. Scope: 'mine' (waiting on me) or 'raised' (waiting on others)."""
	user = frappe.session.user

	filters: dict = {}
	if scope == "mine":
		filters["_assign"] = ("like", f'%"{user}"%')
	elif scope == "raised":
		filters["raised_by"] = user

	return frappe.get_list(
		"Accounting Request",
		filters=filters,
		fields=[
			"name",
			"subject",
			"request_type",
			"status",
			"priority",
			"due_date",
			"reference_doctype",
			"reference_name",
			"context_party",
			"context_amount",
			"context_date",
			"raised_by",
			"_assign",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=200,
	)
