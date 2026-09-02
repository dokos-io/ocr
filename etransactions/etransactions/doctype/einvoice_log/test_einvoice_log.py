# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.tests import UnitTestCase

from etransactions.etransactions.doctype.einvoice_log.einvoice_log import log_fetch


class TesteInvoiceLog(UnitTestCase):
	def _create(self, days_old: int) -> str:
		doc = frappe.get_doc({
			"doctype": "eInvoice Log",
			"operation": "download_flow",
			"status": "success",
			"flow_id": f"FLOW-LOG-{days_old}",
			"request": "download_flow(FLOW-LOG)",
			"response": "12 byte(s), xml",
		}).insert(ignore_permissions=True)
		frappe.db.set_value(
			"eInvoice Log",
			doc.name,
			"creation",
			frappe.utils.add_days(frappe.utils.now_datetime(), -days_old),
			update_modified=False,
		)
		return doc.name

	def test_log_fetch_records_the_call(self):
		log_fetch(
			operation="list_incoming_invoices",
			status="success",
			company="_Test Company",
			flow_id=None,
			request="updated_after=None",
			response="2 flow(s) listed",
		)
		latest = frappe.get_last_doc("eInvoice Log", filters={"operation": "list_incoming_invoices"})
		self.assertEqual(latest.status, "success")
		self.assertEqual(latest.company, "_Test Company")
		self.assertEqual(latest.response, "2 flow(s) listed")

	def test_clear_old_logs_only_removes_entries_past_the_cutoff(self):
		from etransactions.etransactions.doctype.einvoice_log.einvoice_log import eInvoiceLog

		recent = self._create(days_old=10)
		old = self._create(days_old=100)

		eInvoiceLog.clear_old_logs(90)

		self.assertTrue(frappe.db.exists("eInvoice Log", recent), "a log within retention must survive")
		self.assertFalse(frappe.db.exists("eInvoice Log", old), "a log past retention must be cleared")
