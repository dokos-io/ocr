# Copyright (c) 2024, Dokos SAS and Contributors
# See license.txt


from typing import TYPE_CHECKING
from frappe.tests import IntegrationTestCase, change_settings
import frappe
from frappe.utils.data import nowdate

from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

if TYPE_CHECKING:
	from etransactions.etransactions.doctype.pending_purchase_invoice.pending_purchase_invoice import PendingPurchaseInvoice

IGNORE_TEST_RECORD_DEPENDENCIES = ["Supplier", "Company", "Currency", "Tax Category", "Purchase Taxes and Charges Template", "Purchase Invoice", "File", "OCR Request", "Item", "Cost Center", "Project"]

class TestPendingPurchaseInvoice(IntegrationTestCase):
	def setUp(self):
		self.clear_existing_data()
		self.create_prerequisites()

	def tearDown(self):
		frappe.db.rollback()

	def create_prerequisites(self):
		self.supplier = frappe.get_doc("Supplier", "_Test Supplier")
		self.company = "_Test Company"


	def clear_existing_data(self):
		for doctype in ["Purchase Invoice", "Pending Purchase Invoice", "Purchase Receipt", "Purchase Order"]:
			frappe.db.delete(doctype)


	@change_settings(
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	@change_settings("Accounts Settings", {"mandatory_accounting_journal": 0})
	def test_auto_reconciliation_with_purchase_receipt(self):
		po = create_purchase_order(supplier=self.supplier.name, company=self.company, qty=1.0, rate=5000)
		pr = make_purchase_receipt(po.name)
		pr.submit()

		ppi = frappe.get_doc({
			"doctype": "Pending Purchase Invoice",
			"supplier": po.supplier,
			"company": po.company,
			"purchase_order_number": po.name,
			"supplier_net_amount": pr.net_total,
			"bill_no": "123",
			"bill_date": nowdate(),
		})
		ppi.insert()

		pi_name = frappe.db.get_value("Purchase Invoice", {"pending_purchase_invoice": ppi.name})
		self.assertTrue(pi_name)
		pi = frappe.get_doc("Purchase Invoice", pi_name) # type: ignore
		self.assertEqual(pi.total, 5000.0) # type: ignore


	@change_settings(
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	@change_settings("Accounts Settings", {"mandatory_accounting_journal": 0})
	def test_auto_reconciliation_of_credit_note(self):
		po = create_purchase_order(supplier=self.supplier.name, company=self.company, qty=1.0, rate=5000)
		pr = make_purchase_receipt(po.name)
		pr.submit()

		ppi: PendingPurchaseInvoice = frappe.get_doc({
			"doctype": "Pending Purchase Invoice",
			"supplier": po.supplier,
			"company": po.company,
			"purchase_order_number": po.name,
			"supplier_net_amount": pr.net_total,
			"bill_no": "123",
			"bill_date": nowdate(),
		}) # type: ignore
		ppi.insert()

		pi_name = frappe.db.get_value("Purchase Invoice", {"pending_purchase_invoice": ppi.name})
		pi = frappe.get_doc("Purchase Invoice", pi_name) # type: ignore

		credit_note_ppi: PendingPurchaseInvoice = frappe.get_doc({
			"doctype": "Pending Purchase Invoice",
			"supplier": po.supplier,
			"company": po.company,
			"is_return": 1,
			"original_invoice": pi.name,
			"supplier_net_amount": 500,
			"bill_no": "CN-123",
			"bill_date": nowdate(),
		}) # type: ignore
		credit_note_ppi.insert()

		credit_note_ppi.items[0].rate = 500.0
		credit_note_ppi.save()

		cn_name = frappe.db.get_value("Purchase Invoice", {"pending_purchase_invoice": credit_note_ppi.name})
		self.assertTrue(cn_name)
		cn = frappe.get_doc("Purchase Invoice", cn_name) # type: ignore
		self.assertEqual(cn.is_return, 1) # type: ignore
		self.assertEqual(cn.return_against, pi.name) # type: ignore
