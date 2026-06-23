import frappe
from frappe import _

from etransactions.plateforme_agreee.session import get_client
from etransactions.plateforme_agreee.routing import address_for_siret, parse_directory_identifier
from etransactions.etransactions.doctype.einvoicing_log.einvoicing_log import eInvoicingLog


@frappe.whitelist()
def sync_customer_directory(customer: str, company: str = None):
	"""Sync eTransactions Accredited Platform directory lines for a customer. Called from the Customer form."""
	frappe.has_permission("Customer", "write", doc=customer, throw=True)
	if frappe.db.get_value("Customer", customer, "directory_pinned"):
		frappe.msgprint(
			_("Directory is pinned for this customer — unpin to sync."),
			indicator="orange",
		)
		return
	if not frappe.db.get_value("Customer", customer, "siren_number"):
		frappe.throw(_("This customer has no SIREN number. Add one before syncing directory lines."))
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

	new_count = result["new_count"]
	updated_count = result["updated_count"]
	if new_count + updated_count > 0:
		frappe.msgprint(
			_("Directory lines updated: {0} new, {1} updated").format(new_count, updated_count),
			alert=True,
			indicator="green",
		)
		return

	entity_type, closed = frappe.db.get_value(
		"Customer", customer, ["directory_entity_type", "directory_closed"]
	)
	if entity_type == "no" or closed:
		frappe.msgprint(
			_("This customer was not found in the directory (or is closed). No active routing lines."),
			indicator="orange",
		)
	else:
		frappe.msgprint(
			_("Directory is already up to date — no changes."),
			alert=True,
			indicator="blue",
		)


@frappe.whitelist()
def get_party_establishments(party_type: str, party: str) -> list[dict]:
	"""Return the party's addresses (establishments) with their SIRET, buyer
	reference and the directory line bound to each one.

	Used by the master-data readiness wizard's "Establishments & routing" step.
	"""
	if party_type not in ("Customer", "Supplier"):
		frappe.throw(_("Invalid party type {0}.").format(party_type))
	frappe.has_permission(party_type, "read", doc=party, throw=True)

	party_field = "customer" if party_type == "Customer" else "supplier"

	address_names = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "link_doctype": party_type, "link_name": party},
		pluck="parent",
	)
	if not address_names:
		return []

	addresses = frappe.get_all(
		"Address",
		filters={"name": ["in", address_names], "disabled": 0},
		fields=[
			"name", "address_title", "address_type", "siret_number",
			"etransactions_buyer_reference", "is_primary_address",
		],
		order_by="is_primary_address desc, address_title",
	)

	out = []
	for a in addresses:
		line = None
		if a.siret_number:
			line = frappe.db.get_value(
				"eInvoicing Directory Line",
				{party_field: party, "address": a.name},
				["name", "line_status", "routing_code_name", "commitment_required"],
				as_dict=True,
			)
		out.append({
			"address": a.name,
			"title": a.address_title,
			"address_type": a.address_type,
			"siret_number": a.siret_number,
			"buyer_reference": a.etransactions_buyer_reference,
			"is_primary": a.is_primary_address,
			"line": line,
		})
	return out


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
				"directory_pinned": 0,
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
	siren, directory_type, pinned = frappe.db.get_value(
		"Customer", customer_name, ["siren_number", "directory_type", "directory_pinned"]
	)
	if pinned:
		result["logs"].append(("info", f"Customer {customer_name} is directory-pinned. Skipping sync."))
		return
	if not siren:
		result["logs"].append(("warning", f"Customer {customer_name} has no SIREN number. Skipping."))
		return

	directory_data = client.get_directory_for_siren(siren, directory_type)

	frappe.db.set_value("Customer", customer_name, {
		"directory_entity_type": directory_data.entity_type,
		"directory_name": directory_data.name or "",
		"directory_closed": 1 if directory_data.closed else 0,
		"directory_update_date": frappe.utils.nowdate(),
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
		fields=["name", "identifier", "line_status", "routing_code_name", "commitment_required",
			"siren", "siret", "routing_code", "line_type", "address"],
	)
	existing_by_id = {row.identifier: row for row in existing}
	seen_identifiers: set = set()

	tracked_fields = (
		"line_status", "routing_code_name", "commitment_required",
		"siren", "siret", "routing_code", "line_type", "address",
	)

	for identifier, line_data in directory_data.lines.items():
		seen_identifiers.add(identifier)
		parsed = parse_directory_identifier(identifier)
		line_vals = {
			"line_status": line_data.line_status,
			"routing_code_name": line_data.routing_code_name,
			"commitment_required": line_data.commitment_required,
			"siren": parsed["siren"],
			"siret": parsed["siret"],
			"routing_code": parsed["routing_code"],
			"line_type": parsed["line_type"],
			# Bind the line to the matching establishment (Address) when we can.
			"address": address_for_siret("Customer", customer_name, parsed["siret"]),
		}
		if identifier in existing_by_id:
			existing_row = existing_by_id[identifier]
			update = {
				field: line_vals[field]
				for field in tracked_fields
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
