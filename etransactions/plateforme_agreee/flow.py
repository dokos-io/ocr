import frappe
from frappe import _

from etransactions.plateforme_agreee.session import get_client
from etransactions.plateforme_agreee import lifecycle_status
from etransactions.etransactions.doctype.einvoicing_log.einvoicing_log import eInvoicingLog
from etransactions.etransactions.doctype.einvoice_event.einvoice_event import record_event


def send_einvoice_to_plateforme(einvoice_name: str):
	"""Send an outgoing eInvoice to the accredited platform. Called from sales_invoice.on_submit()."""
	einvoice = frappe.get_doc("eInvoice", einvoice_name)

	result = {
		"operation_type": "flow_send",
		"origin": "Submit",
		"company": einvoice.company,
		"new_count": 0,
		"updated_count": 0,
		"logs": [],
	}

	try:
		einvoice.send_to_plateform()
		result["new_count"] = 1
		result["logs"].append(("info", f"eInvoice {einvoice_name} submitted. Flow ID: {einvoice.pa_flow_id}"))
	except Exception as e:
		result["logs"].append(("error", f"Failed to submit eInvoice {einvoice_name}: {str(e)}"))
		eInvoicingLog.create_log(result)
		raise

	eInvoicingLog.create_log(result)


def poll_pending_outgoing_flows():
	"""Cron: poll the PA for status updates on all pending/sent outgoing eInvoices."""
	pending = frappe.get_all(
		"eInvoice",
		filters={
			"einvoice_type": "Outgoing",
			"pa_flow_id": ["is", "set"],
			"pa_status": ["in", ["sent", "pending"]],
		},
		fields=["name", "company", "sales_invoice"],
	)

	clients: dict = {}
	for row in pending:
		company = row.company
		if company not in clients:
			try:
				clients[company] = get_client(company)
			except Exception:
				clients[company] = None

		client = clients.get(company)
		if not client:
			continue

		result = {
			"operation_type": "flow_status",
			"origin": "Cron",
			"company": company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}

		try:
			einvoice = frappe.get_doc("eInvoice", row.name)
			einvoice.refresh_pa_status()
			result["updated_count"] = 1
			result["logs"].append(("info", f"eInvoice {row.name} status updated to {einvoice.pa_status}"))
		except Exception as e:
			result["logs"].append(("warning", f"Failed to refresh status for eInvoice {row.name}: {str(e)}"))

		eInvoicingLog.create_log(result)


def poll_outgoing_lifecycle_events():
	"""Cron: pull counterparty lifecycle events for our outgoing eInvoices.

	Works for platforms that expose events inline on the invoice (SuperPDP);
	CDAR-based platforms (Esalink/AFNOR) return nothing here and are handled by
	``poll_incoming_lifecycle_flows()``.
	"""
	cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -90)
	outgoing = frappe.get_all(
		"eInvoice",
		filters={
			"einvoice_type": "Outgoing",
			"pa_flow_id": ["is", "set"],
			"pa_submitted_at": [">=", cutoff],
		},
		fields=["name", "company", "pa_flow_id"],
	)

	clients: dict = {}
	for row in outgoing:
		company = row.company
		if company not in clients:
			try:
				clients[company] = get_client(company)
			except Exception:
				clients[company] = None
		client = clients.get(company)
		if not client:
			continue

		result = {
			"operation_type": "lifecycle_receive",
			"origin": "Cron",
			"company": company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}
		try:
			for event in client.get_lifecycle_events(row.pa_flow_id):
				created = record_event(
					row.name,
					direction="in",
					status=event.status,
					state="done",
					status_datetime=event.datetime,
					pa_event_id=event.pa_event_id,
					pa_flow_id=row.pa_flow_id,
					reason_code=event.reason_code,
					reason_text=event.reason_text,
					action_code=event.action_code,
					action_text=event.action_text,
					comment=event.comment,
				)
				if created:
					result["new_count"] += 1
					result["logs"].append(
						("info", f"Recorded incoming status '{event.status}' for eInvoice {row.name}")
					)
		except Exception as e:
			result["logs"].append(("warning", f"Could not read lifecycle events for eInvoice {row.name}: {str(e)}"))

		if result["new_count"] or result["logs"]:
			eInvoicingLog.create_log(result)


def poll_incoming_lifecycle_flows():
	"""Cron: fetch incoming CDAR lifecycle flows (Esalink/AFNOR) and record events."""
	try:
		from pyfrctc import parse_cdar
	except ImportError:
		parse_cdar = None

	active_platforms = frappe.get_all(
		"eTransactions Accredited Platform",
		filters={"is_active": 1},
		fields=["company"],
		group_by="company",
	)

	for company_row in active_platforms:
		company = company_row.company
		result = {
			"operation_type": "lifecycle_receive",
			"origin": "Cron",
			"company": company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}

		try:
			client = get_client(company)
			lc_flows = client.list_incoming_lifecycle_flows()
		except Exception as e:
			result["logs"].append(("error", f"Failed to list lifecycle flows: {str(e)}"))
			eInvoicingLog.create_log(result)
			continue

		if lc_flows and parse_cdar is None:
			result["logs"].append(("error", "pyfrctc is required to parse incoming CDAR flows."))
			eInvoicingLog.create_log(result)
			continue

		for flow in lc_flows:
			if not flow.flow_id:
				continue
			if frappe.db.exists("eInvoice Event", {"pa_event_id": flow.flow_id}):
				continue
			try:
				content = client.download_flow(flow.flow_id)
				parsed = parse_cdar(content)
			except Exception as e:
				result["logs"].append(("warning", f"Could not parse CDAR flow {flow.flow_id}: {str(e)}"))
				continue

			canonical = lifecycle_status.from_cdar_code(parsed.get("status_code"))
			if not canonical:
				continue

			einvoice = frappe.db.get_value(
				"eInvoice", {"id": parsed.get("invoice_number"), "company": company}, "name"
			)
			if not einvoice:
				result["logs"].append(
					("warning", f"No matching eInvoice for CDAR flow {flow.flow_id} (invoice {parsed.get('invoice_number')})")
				)
				continue

			detail = (parsed.get("doc_status") or [{}])[0]
			created = record_event(
				einvoice,
				direction="in",
				status=canonical,
				state="done",
				status_datetime=parsed.get("lc_datetime"),
				pa_event_id=flow.flow_id,
				pa_flow_id=flow.flow_id,
				reason_code=detail.get("reason_code"),
				reason_text=detail.get("reason_txt"),
				action_code=detail.get("action_code"),
				action_text=detail.get("action_txt"),
				comment=detail.get("comment"),
			)
			if created:
				result["new_count"] += 1
				result["logs"].append(("info", f"Recorded incoming status '{canonical}' for eInvoice {einvoice}"))

		if result["new_count"] or result["logs"]:
			eInvoicingLog.create_log(result)


def poll_incoming_flows():
	"""Cron: fetch new incoming flows from the PA and create eInvoice records for each."""
	active_platforms = frappe.get_all(
		"eTransactions Accredited Platform",
		filters={"is_active": 1, "transaction_type": ["in", ["Purchases", "Both"]]},
		fields=["company"],
		group_by="company",
	)

	for company_row in active_platforms:
		company = company_row.company

		result = {
			"operation_type": "flow_receive",
			"origin": "Cron",
			"company": company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}

		try:
			client = get_client(company, transaction_type="purchases")
		except Exception as e:
			result["logs"].append(("error", str(e)))
			eInvoicingLog.create_log(result)
			continue

		try:
			incoming_flows = client.list_incoming_invoices()
		except Exception as e:
			result["logs"].append(("error", f"Failed to list incoming invoices: {str(e)}"))
			eInvoicingLog.create_log(result)
			continue

		known_flow_ids = set(
			frappe.get_all("eInvoice", filters={"pa_flow_id": ["is", "set"]}, pluck="pa_flow_id")
		)

		for flow in incoming_flows:
			if not flow.flow_id or flow.flow_id in known_flow_ids:
				continue

			try:
				file_content = client.download_flow(flow.flow_id)
			except Exception as e:
				result["logs"].append(("warning", f"Could not download flow {flow.flow_id}: {str(e)}"))
				continue

			try:
				from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice
				eInvoice.create_from_plateforme_flow(flow, file_content, company)
				result["new_count"] += 1
				known_flow_ids.add(flow.flow_id)
				result["logs"].append(("info", f"Created eInvoice from incoming flow {flow.flow_id}"))
			except Exception as e:
				result["logs"].append(("error", f"Failed to create eInvoice from flow {flow.flow_id}: {str(e)}"))

		eInvoicingLog.create_log(result)
