# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""The fixture endpoints the Cypress suite drives.

The specs assert on what these produce, so a break here shows up as a confusing DOM
failure in the UI job — which is slow, non-blocking and runs after the Python suite.
Covering them here means the fixture breaks in the fast, blocking job instead.

They are also the only place the full inbound chain runs end to end from the cron entry
point: poll -> eInvoice -> content fetch -> prefilled Supplier Invoice.
"""

import frappe

from etransactions.tests.fixtures import (
	clear_platforms,
	ensure_default_expense_account,
	seed_company,
	seed_item,
)
from etransactions.tests.ui_test_fixtures import (
	SUPPLIER,
	SUPPLIER_TAX_ID,
	receive_incoming_flow,
	record_lifecycle_event,
)
from etransactions.tests.utils import eTransactionsTestSuite

COMPANY = "_Test Company"


class TestUIFixtureEndpoints(eTransactionsTestSuite):
	def setUp(self):
		super().setUp()
		seed_company(COMPANY)
		ensure_default_expense_account(COMPANY)
		seed_item()
		clear_platforms(COMPANY)
		self._make_supplier()
		self._make_platform()
		# Same switches make_fixtures() sets: a received invoice references no Purchase
		# Order, and the auto-sends would enqueue a job reaching for a platform.
		frappe.db.set_single_value(
			"eTransactions Settings",
			{"enable_einvoicing": 1, "no_purchase_order": 1, "auto_send_in_hand": 0},
		)
		frappe.clear_cache(doctype="eTransactions Settings")

	def _make_supplier(self):
		if not frappe.db.exists("Supplier", SUPPLIER):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": SUPPLIER,
					"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
					"country": "France",
					"tax_id": SUPPLIER_TAX_ID,
				}
			).insert(ignore_if_duplicate=True, ignore_permissions=True)
		else:
			frappe.db.set_value("Supplier", SUPPLIER, "tax_id", SUPPLIER_TAX_ID, update_modified=False)

	def _make_platform(self):
		frappe.get_doc(
			{
				"doctype": "eTransactions Accredited Platform",
				"platform_name": "UI Fixture Platform",
				"platform_type": "Custom",
				"platform_code": "UIFIX",
				"company": COMPANY,
				"transaction_type": "Both",
				"is_active": 1,
				"api_base_url": "http://localhost:1/never-called",
				"client_id": "ui-fixture",
				"client_secret": "ui-fixture-secret",
			}
		).insert(ignore_permissions=True)

	# ------------------------------------------------------------------
	def test_the_cron_entry_point_produces_a_prefilled_supplier_invoice(self):
		result = receive_incoming_flow(flow_id="UI-FIXTURE-1", company=COMPANY)

		einvoice = frappe.get_doc("eInvoice", result["einvoice"])
		self.assertEqual(einvoice.einvoice_type, "Incoming")
		self.assertEqual(einvoice.pa_flow_id, "UI-FIXTURE-1")
		# The content fetch has to have run inline: the spec navigates straight to the
		# Supplier Invoice, and nothing would ever drain a queued job in the UI job.
		self.assertEqual(einvoice.pa_content_state, "fetched")
		self.assertEqual(einvoice.seller_name, "LE FOURNISSEUR")

		self.assertTrue(result["supplier_invoice"], "the eInvoice must generate a Supplier Invoice")
		supplier_invoice = frappe.get_doc("Supplier Invoice", result["supplier_invoice"])
		self.assertEqual(supplier_invoice.einvoice, einvoice.name)
		self.assertEqual(supplier_invoice.bill_no, einvoice.id)
		# Matching tax ids are what bind the received invoice to a real Supplier; without
		# this the "prefilled data" the specs assert on would just be raw parse output.
		self.assertEqual(supplier_invoice.supplier, SUPPLIER)
		self.assertTrue(supplier_invoice.items, "the fixture invoice must carry line items")

	def test_the_received_file_is_attached_to_the_supplier_invoice(self):
		"""The preview reads `file`; an Accounts User cannot read the eInvoice's copy."""
		result = receive_incoming_flow(flow_id="UI-FIXTURE-2", company=COMPANY)

		supplier_invoice = frappe.get_doc("Supplier Invoice", result["supplier_invoice"])
		self.assertTrue(supplier_invoice.file)
		self.assertEqual(
			frappe.db.get_value("File", supplier_invoice.file, "attached_to_doctype"),
			"Supplier Invoice",
		)

	def test_a_recorded_event_lands_on_the_timeline(self):
		result = receive_incoming_flow(flow_id="UI-FIXTURE-3", company=COMPANY)
		record_lifecycle_event(result["einvoice"], "in_hand")

		events = frappe.get_all(
			"eInvoice Event", filters={"einvoice": result["einvoice"]}, pluck="status"
		)
		self.assertIn("in_hand", events)
		self.assertEqual(frappe.db.get_value("eInvoice", result["einvoice"], "pa_status"), "done")

	def test_the_purchase_invoice_carries_the_einvoice_link(self):
		"""The Purchase Invoice must surface the eInvoice, which is what the spec asserts."""
		result = receive_incoming_flow(flow_id="UI-FIXTURE-4", company=COMPANY)

		supplier_invoice = frappe.get_doc("Supplier Invoice", result["supplier_invoice"])
		# The received lines carry the seller's own product ids, which match no Dokos
		# Item, so a Purchase Invoice line would have no expense account to inherit.
		# Picking the item is the accountant's step, and the Cypress spec does it on the
		# grid; here it is set directly.
		for item in supplier_invoice.items:
			item.item_code = "_Test Item 1"
		# The fixture invoice is denominated in EUR, while the shared test company keeps
		# whatever currency erpnext's fixtures gave it. A Purchase Invoice in a foreign
		# currency needs a payable account and an exchange rate in that currency, neither
		# of which this asserts — and the UI company, being French, never hits the case.
		supplier_invoice.currency = frappe.get_cached_value("Company", COMPANY, "default_currency")
		supplier_invoice.save()

		purchase_invoice = supplier_invoice.create_purchase_invoice()

		self.assertEqual(purchase_invoice.supplier_invoice, supplier_invoice.name)
		self.assertEqual(purchase_invoice.einvoice, result["einvoice"])
