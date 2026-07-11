# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""End-to-end e-reporting tests (SuperPDP — the only e-reporting-capable mode).

Drives the B2C/B2Bi capture → batch submit → declaration-poll pipeline over real
HTTP to the Microcks SuperPDP mock. See :mod:`.base` for the harness/skip contract.
"""

import frappe

from etransactions.plateforme_agreee import flow
from etransactions.tests.integration.base import COMPANY, MicrocksTestCase


class TestEReportingE2E(MicrocksTestCase):
	def setUp(self):
		super().setUp()
		# E-reporting is a SuperPDP capability; make it the active platform.
		self.use_platform("SuperPDP")
		# Avoid the Factur-X-on-submit path (wkhtmltopdf) during Sales Invoice submit.
		frappe.db.set_value(
			"eTransactions Settings", None, "generate_facturx_on_submit", 0, update_modified=False
		)

	def _submit_b2c_sale(self, customer_name: str):
		"""Submit a B2C Sales Invoice (no profile → only the e-reporting capture runs)."""
		customer = self.make_customer(customer_name, entity_type="private_inactive")
		currency = frappe.db.get_value("Company", COMPANY, "default_currency") or "EUR"
		si = frappe.new_doc("Sales Invoice")
		si.company = COMPANY
		si.customer = customer
		si.currency = currency
		si.posting_date = frappe.utils.today()
		si.append("items", {"item_code": "_Test Item 1", "qty": 1, "rate": 100.0})
		tax_account = frappe.db.get_value(
			"Account", {"account_type": "Tax", "company": COMPANY, "is_group": 0}, "name"
		)
		if tax_account:
			si.append(
				"taxes",
				{"charge_type": "On Net Total", "account_head": tax_account, "rate": 20.0, "description": "TVA 20%"},
			)
		si.flags.ignore_permissions = True
		si.insert()
		si.submit()
		return si

	def _entries(self, si_name, kind="transaction"):
		return frappe.get_all(
			"eReporting Entry",
			filters={"reference_doctype": "Sales Invoice", "reference_name": si_name, "kind": kind},
			fields=["name", "state", "pa_entry_id", "transaction_class", "role_code"],
		)

	def test_b2c_sale_is_captured(self):
		"""Submitting a B2C sale queues a pending transaction e-reporting entry."""
		si = self._submit_b2c_sale("_Test B2C Cap")
		entries = self._entries(si.name)
		self.assertEqual(len(entries), 1)
		self.assertEqual(entries[0].state, "pending")
		self.assertEqual(entries[0].transaction_class, "B2C")
		self.assertEqual(entries[0].role_code, "SE")

	def test_submit_pending_entries_marks_sent(self):
		"""The batch submitter POSTs to SuperPDP and stores the returned entry id."""
		si = self._submit_b2c_sale("_Test B2C Send")
		flow.submit_pending_ereporting_entries()
		entry = self._entries(si.name)[0]
		self.assertEqual(entry.state, "sent")
		self.assertEqual(entry.pa_entry_id, "50001")

	def test_count_mismatch_marks_error(self):
		"""When the platform returns fewer rows than submitted, entries are flagged."""
		si1 = self._submit_b2c_sale("_Test B2C Mm1")
		si2 = self._submit_b2c_sale("_Test B2C Mm2")
		# Two pending transaction entries; the mock returns one row → mismatch → error.
		flow.submit_pending_ereporting_entries()
		for si in (si1, si2):
			self.assertEqual(self._entries(si.name)[0].state, "error")

	def test_poll_status_upserts_declaration(self):
		"""Polling e-reporting status records the PPF declaration returned by the mock."""
		flow.poll_ereporting_status()
		decl = frappe.get_all(
			"eReporting Declaration", filters={"company": COMPANY}, fields=["name", "pa_ereporting_id"]
		)
		self.assertTrue(decl)
		self.assertTrue(any(d.pa_ereporting_id == "40001" for d in decl))

	def test_b2c_send_is_blocked(self):
		"""A B2C invoice cannot be pushed to the structured-invoice endpoint."""
		customer = self.make_customer("_Test B2C Block", entity_type="private_inactive")
		einvoice = self.make_einvoice(customer, attach_pdf=False)
		self.assertEqual(einvoice.pa_processing_rule, "B2C")
		with self.assertRaises(frappe.ValidationError):
			einvoice.send_to_plateform()
