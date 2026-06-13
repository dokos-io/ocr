# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe

no_cache = 1


def get_context(context):
	context.site_name = frappe.local.site
	context.favicon = frappe.db.get_single_value("Website Settings", "favicon") or ""

	if frappe.session.user != "Guest":
		context.csrf_token = frappe.sessions.get_csrf_token()
		frappe.db.commit()

	return context
