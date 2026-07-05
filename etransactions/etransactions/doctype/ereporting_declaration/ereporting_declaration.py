# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from etransactions.plateforme_agreee import ereporting_status


class eReportingDeclaration(Document):
	@classmethod
	def upsert_from_platform(cls, company: str, result) -> "eReportingDeclaration":
		"""Create or update a declaration from a platform EreportingResult.

		Keyed on the platform e-reporting id so repeated polls are idempotent.
		Returns the saved document.
		"""
		name = frappe.db.get_value(
			"eReporting Declaration", {"pa_ereporting_id": result.id}, "name"
		)
		doc = (
			frappe.get_doc("eReporting Declaration", name)
			if name
			else frappe.new_doc("eReporting Declaration")
		)

		doc.company = company
		doc.kind = result.kind
		doc.role_code = result.role_code
		doc.period_start = result.start_period
		doc.period_end = result.end_period
		doc.pa_ereporting_id = result.id
		doc.pa_status = ereporting_status.derive_state(
			[ev.status_code for ev in result.events]
		)
		doc.pa_updated_at = now_datetime()

		doc.set("events", [])
		for ev in result.events:
			doc.append(
				"events",
				{
					"status_code": ev.status_code,
					"state": ereporting_status.state_for(ev.status_code),
					"status_datetime": ev.created_at,
				},
			)

		doc.save(ignore_permissions=True)
		return doc
