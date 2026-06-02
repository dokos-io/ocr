import frappe
from frappe import _

from etransactions.plateforme_agreee.session import get_client
from etransactions.etransactions.doctype.einvoicing_log.einvoicing_log import eInvoicingLog


@frappe.whitelist()
def sync_customer_directory(customer: str, company: str = None):
	"""Sync eTransactions Accredited Platform directory lines for a customer. Called from the Customer form."""
	if not company:
		company = frappe.defaults.get_global_default("company")
	client = get_client(company, customer=customer)

	result = {
		"operation_type": "directory_single",
		"origin": "Manual",
		"company": company,
		"new_count": 0,
		"updated_count": 0,
		"logs": [],
	}

	_sync_customer_directory(customer, client, result)
	eInvoicingLog.create_log(result)

	frappe.msgprint(
		_("Directory lines updated: {0} new, {1} updated").format(result["new_count"], result["updated_count"]),
		alert=True,
		indicator="green" if result["updated_count"] + result["new_count"] >= 0 else "orange",
	)


def sync_all_customers():
	"""Cron entry point: sync stale directory lines for all customers across all configured companies."""
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
			client = get_client(company)
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
				_sync_customer_directory(customer_name, client, result)
			except Exception as e:
				result["logs"].append(("warning", f"Failed to sync customer {customer_name}: {str(e)}"))

		eInvoicingLog.create_log(result)


def _sync_customer_directory(customer_name: str, client, result: dict):
	"""Query the PA directory for a customer and create/update/archive its directory lines."""
	siren = frappe.db.get_value("Customer", customer_name, "siren_number")
	if not siren:
		result["logs"].append(("warning", f"Customer {customer_name} has no SIREN number. Skipping."))
		return

	directory_data = client.get_directory_for_siren(siren)

	frappe.db.set_value("Customer", customer_name, {
		"directory_entity_type": directory_data.entity_type,
		"directory_name": directory_data.name or "",
		"directory_closed": 1 if directory_data.closed else 0,
		"directory_update_date": frappe.utils.nowdate(),
		"directory_siren": siren,
	})

	if directory_data.entity_type == "no" or directory_data.closed:
		frappe.db.set_value(
			"eInvoicing Directory Line",
			{"customer": customer_name, "line_status": ["!=", "disabled"]},
			"line_status",
			"disabled",
		)
		result["logs"].append((
			"info",
			f"Customer {customer_name} is not in directory or closed. Lines disabled.",
		))
		return

	existing = frappe.get_all(
		"eInvoicing Directory Line",
		filters={"customer": customer_name},
		fields=["name", "identifier", "line_status", "routing_code_name", "commitment_required"],
	)
	existing_by_id = {row.identifier: row for row in existing}
	seen_identifiers: set = set()

	for identifier, line_data in directory_data.lines.items():
		seen_identifiers.add(identifier)
		line_vals = {
			"line_status": line_data.line_status,
			"routing_code_name": line_data.routing_code_name,
			"commitment_required": line_data.commitment_required,
		}
		if identifier in existing_by_id:
			existing_row = existing_by_id[identifier]
			update = {
				field: line_vals[field]
				for field in ("line_status", "routing_code_name", "commitment_required")
				if line_vals.get(field) != existing_row.get(field)
			}
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

	for identifier, existing_row in existing_by_id.items():
		if identifier not in seen_identifiers and existing_row.line_status != "disabled":
			frappe.db.set_value("eInvoicing Directory Line", existing_row.name, "line_status", "disabled")
			result["updated_count"] += 1

	result["logs"].append((
		"info",
		f"Customer {customer_name}: {result['new_count']} new, {result['updated_count']} updated directory lines",
	))
