# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

from frappe import _


def get_dashboard_data(data: dict) -> dict:
	"""Add the Accounting Hub collaboration connections to a reference doctype dashboard."""
	data.setdefault("non_standard_fieldnames", {})["Accounting Request"] = "reference_name"
	data.setdefault("transactions", []).append(
		{"label": _("Collaboration"), "items": ["Accounting Request"]}
	)
	return data


def add_einvoice_connection(data: dict) -> dict:
	"""Link a purchase document back to the e-invoice it was created from.

	Registered per doctype in hooks.py rather than folded into ``get_dashboard_data``:
	the dashboard payload does not say which doctype it belongs to, so the hook
	registration is the only place that knows.
	"""
	data.setdefault("transactions", []).append({"label": _("e-Invoicing"), "items": ["eInvoice"]})
	return data
