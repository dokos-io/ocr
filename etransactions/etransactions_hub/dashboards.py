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
