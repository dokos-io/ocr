# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
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


def _request_counts(user: str) -> dict:
	"""Open-request counters scoped to a user. Caller must check Accounting Request permission."""
	return {
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
	}


def _inbox_to_triage() -> int:
	"""Inbox items still needing triage, or 0 when the user can't see the inbox."""
	if not frappe.has_permission("Accounting Inbox Item"):
		return 0
	return frappe.db.count("Accounting Inbox Item", {"status": ("in", ("To Triage", "In Progress"))})


def _current_closing_period() -> dict | None:
	"""The most recent non-completed closing period, or None (also None without permission)."""
	if not frappe.has_permission("Closing Period"):
		return None
	current_period = frappe.get_all(
		"Closing Period",
		filters={"status": ("!=", "Completed")},
		fields=["name", "title", "progress", "status", "period_end"],
		order_by="period_end desc",
		limit=1,
	)
	return current_period[0] if current_period else None


@frappe.whitelist()
def get_counts() -> dict:
	"""Aggregated counters for the Accounting Hub home screen."""
	frappe.has_permission("Accounting Request", throw=True)

	counts = _request_counts(frappe.session.user)
	counts["inbox_to_triage"] = _inbox_to_triage()
	counts["closing"] = _current_closing_period()

	return counts


def _resolve_company(company: str | None) -> str | None:
	"""Use the given company, else the user's default, else the first company."""
	if company:
		return company
	return frappe.defaults.get_user_default("Company") or frappe.db.get_value("Company", {}, "name")


def _aging(doctype: str, company: str) -> dict:
	"""Outstanding total + days-overdue buckets for submitted invoices of `doctype`."""
	from frappe.utils import date_diff, flt

	buckets = {"current": 0.0, "d1_30": 0.0, "d31_60": 0.0, "d61_90": 0.0, "d90_plus": 0.0}
	total = 0.0
	today = nowdate()

	rows = frappe.get_all(
		doctype,
		filters={"docstatus": 1, "company": company, "outstanding_amount": (">", 0)},
		fields=["outstanding_amount", "due_date"],
	)
	for row in rows:
		amount = flt(row.outstanding_amount)
		total += amount
		days = date_diff(today, row.due_date) if row.due_date else 0
		if days <= 0:
			buckets["current"] += amount
		elif days <= 30:
			buckets["d1_30"] += amount
		elif days <= 60:
			buckets["d31_60"] += amount
		elif days <= 90:
			buckets["d61_90"] += amount
		else:
			buckets["d90_plus"] += amount

	return {"total": total, "buckets": buckets}


def _treasury(company: str) -> dict:
	"""Sum of bank-account balances (company currency) + count of unreconciled transactions."""
	from erpnext.accounts.utils import get_balance_on

	today = nowdate()
	bank_accounts = frappe.get_all(
		"Account",
		filters={"account_type": "Bank", "company": company, "is_group": 0},
		pluck="name",
	)
	bank_balance = sum(get_balance_on(account, today) for account in bank_accounts)

	unreconciled = frappe.db.count(
		"Bank Transaction",
		{"company": company, "docstatus": 1, "status": ("in", ("Pending", "Unreconciled"))},
	)

	return {
		"bank_balance": bank_balance,
		"unreconciled_count": unreconciled,
		"currency": frappe.get_cached_value("Company", company, "default_currency"),
	}


def _data_quality(company: str) -> dict:
	"""Accounting-accuracy signals: missing justificatives, low-confidence invoices, readiness."""
	data: dict = {
		"missing_justificative_open": frappe.db.count(
			"Accounting Request",
			{"request_type": "Missing Justificative", "status": ("in", OPEN_REQUEST_STATUSES)},
		)
	}

	if frappe.has_permission("Supplier Invoice"):
		data["supplier_invoices_low_confidence"] = frappe.db.count(
			"Supplier Invoice", {"status": "Ready", "match_confidence": ("in", ("low", "medium"))}
		)

	# Readiness scans are company-agnostic today (all customers/items); acceptable for v1.
	from etransactions.etransactions.api.widgets import (
		get_customer_readiness_data,
		get_item_tax_readiness_data,
	)

	if frappe.has_permission("Customer"):
		data["customer_readiness_pct"] = get_customer_readiness_data().get("ready_pct")
	if frappe.has_permission("Item"):
		data["item_readiness_pct"] = get_item_tax_readiness_data().get("ready_pct")

	return data


@frappe.whitelist()
def get_overview(company: str | None = None) -> dict:
	"""Internal accounting cockpit KPIs for one company. Sections omitted without permission."""
	frappe.has_permission("Accounting Request", throw=True)

	company = _resolve_company(company)
	overview: dict = {
		"company": company,
		"collaboration": {**_request_counts(frappe.session.user), "inbox_to_triage": _inbox_to_triage()},
		"close": {"period": _current_closing_period()},
		"data_quality": _data_quality(company),
	}

	if company and frappe.has_permission("Bank Transaction"):
		overview["treasury"] = _treasury(company)
	if company and frappe.has_permission("Sales Invoice"):
		overview["receivables"] = _aging("Sales Invoice", company)
	if company and frappe.has_permission("Purchase Invoice"):
		overview["payables"] = _aging("Purchase Invoice", company)

	return overview


@frappe.whitelist()
def get_inbox(
	status: str | None = None,
	source: str | None = None,
	company: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	search: str | None = None,
) -> list[dict]:
	"""Inbox items for the triage list, with optional filters."""
	filters: dict = {}
	if status:
		filters["status"] = status
	if source:
		filters["source"] = source
	if company:
		filters["company"] = company
	if from_date and to_date:
		filters["creation"] = ("between", [from_date, f"{to_date} 23:59:59"])
	elif from_date:
		filters["creation"] = (">=", from_date)
	elif to_date:
		filters["creation"] = ("<=", f"{to_date} 23:59:59")

	or_filters = {}
	if search:
		or_filters = {
			"title": ("like", f"%{search}%"),
			"subject": ("like", f"%{search}%"),
			"sender": ("like", f"%{search}%"),
		}

	return frappe.get_list(
		"Accounting Inbox Item",
		filters=filters,
		or_filters=or_filters,
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
		fields=["name", "full_name", "user_image"],
		order_by="full_name asc",
		ignore_permissions=True,
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


@frappe.whitelist()
def get_closing_meta() -> dict:
	"""Permission flags and template list for the in-app closing management UI."""
	can_manage_periods = bool(frappe.has_permission("Closing Period", "create"))
	can_manage_templates = bool(frappe.has_permission("Closing Checklist Template", "create"))

	templates = []
	if frappe.has_permission("Closing Checklist Template"):
		templates = frappe.get_all(
			"Closing Checklist Template",
			fields=["name", "template_name", "company", "frequency"],
			order_by="template_name asc",
		)

	return {
		"can_manage_periods": can_manage_periods,
		"can_manage_templates": can_manage_templates,
		"templates": templates,
	}


@frappe.whitelist()
def get_checklist_template(name: str) -> dict:
	"""Full checklist template with its task items, for in-app editing."""
	template = frappe.get_doc("Closing Checklist Template", name)
	template.check_permission("read")
	return template.as_dict()


@frappe.whitelist()
def save_checklist_template(template: str) -> str:
	"""Create or update a Closing Checklist Template (with its items) from the SPA."""
	data = frappe.parse_json(template)

	if data.get("name") and frappe.db.exists("Closing Checklist Template", data["name"]):
		doc = frappe.get_doc("Closing Checklist Template", data["name"])
		doc.check_permission("write")
	else:
		doc = frappe.new_doc("Closing Checklist Template")
		if not frappe.has_permission("Closing Checklist Template", "create"):
			frappe.throw(_("Not permitted to create checklist templates"), frappe.PermissionError)

	doc.template_name = data.get("template_name")
	doc.company = data.get("company")
	doc.frequency = data.get("frequency") or "Monthly"

	doc.set("items", [])
	for item in data.get("items") or []:
		doc.append(
			"items",
			{
				"task_subject": item.get("task_subject"),
				"default_assignee": item.get("default_assignee"),
				"day_offset": item.get("day_offset") or 0,
				"description": item.get("description"),
				"route": item.get("route"),
			},
		)

	doc.save()
	return doc.name


@frappe.whitelist()
def update_closing_period(name: str, period_start: str, period_end: str) -> str:
	"""Update the dates of an existing Closing Period from the SPA."""
	period = frappe.get_doc("Closing Period", name)
	period.check_permission("write")
	period.period_start = period_start
	period.period_end = period_end
	period.save()
	return period.name


@frappe.whitelist()
def delete_closing_period(name: str) -> None:
	"""Delete a Closing Period and its tasks from the SPA."""
	period = frappe.get_doc("Closing Period", name)
	period.check_permission("delete")

	for task in frappe.get_all("Closing Task", filters={"closing_period": name}, pluck="name"):
		frappe.delete_doc("Closing Task", task)

	frappe.delete_doc("Closing Period", name)
