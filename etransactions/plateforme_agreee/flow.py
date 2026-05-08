import frappe
from frappe import _

from etransactions.plateforme_agreee.session import get_client
from etransactions.etransactions.doctype.einvoicing_log.einvoicing_log import eInvoicingLog


def send_einvoice_to_plateforme(einvoice_name: str):
	"""Send an outgoing eInvoice to the Plateforme Agréée. Called from sales_invoice.on_submit()."""
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
		einvoice.send_to_plateforme()
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
