import frappe
from frappe import _

from etransactions.plateforme_agreee.session import get_session
from etransactions.etransactions.doctype.einvoicing_log.einvoicing_log import eInvoicingLog


@frappe.whitelist()
def sync_customer_directory(customer: str):
	"""Sync eTransactions Accredited Platform directory lines for a customer. Called from the Customer form."""
	company = frappe.db.get_value("Customer", customer, "default_company") \
		or frappe.defaults.get_global_default("company")
	session = get_session(company, customer=customer)

	result = {
		"operation_type": "directory_single",
		"origin": "Manual",
		"company": company,
		"new_count": 0,
		"updated_count": 0,
		"logs": [],
	}

	_sync_customer_directory(customer, session, result)
	eInvoicingLog.create_log(result)

	frappe.msgprint(
		_("Directory lines updated: {0} new, {1} updated").format(result["new_count"], result["updated_count"]),
		alert=True,
		indicator="green" if result["updated_count"] + result["new_count"] >= 0 else "orange",
	)


def sync_all_customers():
	"""Cron entry point: sync stale directory lines for all customers across all configured companies."""
	# Get all companies that have an active eTransactions Accredited Platform
	companies = frappe.db.get_all(
		"eTransactions Accredited Platform",
		fields=["company", "directory_refresh_days"],
		filters={"is_active": 1},
		group_by="company"
	)

	for platform_row in companies:
		company = platform_row.company
		refresh_days = platform_row.directory_refresh_days or 15

		result = {
			"operation_type": "directory_all",
			"origin": "Cron",
			"company": company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}

		try:
			session = get_session(company)
		except Exception as e:
			result["logs"].append(("error", str(e)))
			eInvoicingLog.create_log(result)
			continue

		cutoff_date = frappe.utils.add_days(frappe.utils.nowdate(), -refresh_days)
		stale_customers = frappe.get_all(
			"Customer",
			filters={
				"directory_entity_type": ["in", ["private", "public"]],
				"directory_closed": 0,
				"directory_update_date": ["<", cutoff_date],
			},
			pluck="name",
		)

		result["logs"].append(("info", f"Syncing {len(stale_customers)} customers for company {company}"))

		for customer_name in stale_customers:
			try:
				_sync_customer_directory(customer_name, session, result)
			except Exception as e:
				result["logs"].append(("warning", f"Failed to sync customer {customer_name}: {str(e)}"))

		eInvoicingLog.create_log(result)


def _sync_customer_directory(customer_name: str, session, result: dict):
	"""Query the PA directory for a customer and create/update/archive its directory lines."""
	try:
		from pyfrctc import get_directory_siren_parsed, get_directory_lines_parsed
	except ImportError:
		frappe.throw(_("The pyfrctc library is not installed."))

	siren = frappe.db.get_value("Customer", customer_name, "tax_id")
	if not siren:
		result["logs"].append(("warning", f"Customer {customer_name} has no tax_id (SIREN). Skipping."))
		return

	siren_parsed = get_directory_siren_parsed(session, siren)
	entity_type = siren_parsed.get("entity_type", "no")

	frappe.db.set_value("Customer", customer_name, {
		"directory_entity_type": entity_type,
		"directory_name": siren_parsed.get("name") or "",
		"directory_closed": 1 if siren_parsed.get("closed") else 0,
		"directory_update_date": frappe.utils.nowdate(),
		"directory_siren": siren,
	})

	if entity_type == "no" or siren_parsed.get("closed"):
		# Disable all existing active lines
		frappe.db.set_value(
			"eInvoicing Directory Line",
			{"customer": customer_name, "line_status": ["!=", "disabled"]},
			"line_status",
			"disabled",
		)
		result["logs"].append(("info", f"Customer {customer_name} is not in directory or closed. Lines disabled."))
		return

	api_lines = get_directory_lines_parsed(session, siren, siren_parsed)

	existing = frappe.get_all(
		"eInvoicing Directory Line",
		filters={"customer": customer_name},
		fields=["name", "identifier", "line_status", "routing_code_name", "commitment_required"],
	)
	existing_by_id = {row.identifier: row for row in existing}
	seen_identifiers = set()

	for identifier, line_vals in api_lines.items():
		seen_identifiers.add(identifier)
		if identifier in existing_by_id:
			existing_row = existing_by_id[identifier]
			update = {}
			for field in ("line_status", "routing_code_name", "commitment_required"):
				if line_vals.get(field) != existing_row.get(field):
					update[field] = line_vals.get(field)
			if update:
				frappe.db.set_value("eInvoicing Directory Line", existing_row.name, update)
				result["updated_count"] += 1
		else:
			frappe.get_doc({
				"doctype": "eInvoicing Directory Line",
				"customer": customer_name,
				"identifier": identifier,
				**line_vals,
			}).insert(ignore_permissions=True)
			result["new_count"] += 1

	# Archive lines no longer returned by the API
	for identifier, existing_row in existing_by_id.items():
		if identifier not in seen_identifiers and existing_row.line_status != "disabled":
			frappe.db.set_value("eInvoicing Directory Line", existing_row.name, "line_status", "disabled")
			result["updated_count"] += 1

	result["logs"].append((
		"info",
		f"Customer {customer_name}: {result['new_count']} new, {result['updated_count']} updated directory lines",
	))
