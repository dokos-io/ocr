from random import choice
import time
import frappe
from frappe.tests import IntegrationTestCase, change_settings
from frappe.utils import add_days, flt, nowdate
from frappe.utils.make_random import get_random

from erpnext import get_default_company

from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder, make_purchase_receipt
from etransactions.etransactions.doctype.etransactions_settings.etransactions_settings import eTransactionsSettings
from etransactions.tests.utils import add_items, add_suppliers
from etransactions.etransactions.doctype.supplier_invoice.supplier_invoice import SupplierInvoice

IGNORE_TEST_RECORD_DEPENDENCIES = []

class TestAutoReconciliation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		cls.items = add_items()
		add_suppliers()

		frappe.db.set_single_value("Accounts Settings", "add_taxes_from_item_tax_template", 1)

	@change_settings(
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	def test_auto_reconciliation_01(self):
		"""
		Purchase order is received
		Purchase receipt and supplier invoice match perfectly
		"""
		purchase_order = get_purchase_order(
			company=get_default_company(),
			item_code=choice(self.items), # type: ignore
			qty=10,
			rate=500
		) # type: ignore
		purchase_order.insert()
		purchase_order.submit()

		purchase_receipt = make_purchase_receipt(purchase_order.name)
		purchase_receipt.insert()
		purchase_receipt.submit()

		pending_purchase_invoice = get_pending_purchase_invoice(
			supplier = purchase_order.supplier,
			amount = purchase_receipt.net_total,
			purchase_order = purchase_order.name
		)

		pending_purchase_invoice.insert(ignore_permissions=True, ignore_mandatory=True)

		self.assertEqual(len(pending_purchase_invoice.items), 1)
		self.assertIn(purchase_receipt.name, [r.reference_docname for r in pending_purchase_invoice.items])
		pending_purchase_invoice.reload()
		self.assertEqual(pending_purchase_invoice.status, "Completed")


	@change_settings(
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	) # type: ignore
	def test_auto_reconciliation_02(self):
		"""
		Purchase order is received
		Supplier invoice is higher than purchase order. When an allowance is set, it is correctly integrated.
		"""
		purchase_order = get_purchase_order(
			company=get_default_company(),
			item_code=choice(self.items), # type: ignore
			qty=1,
			rate=5000
		) # type: ignore
		purchase_order.insert()
		purchase_order.submit()

		purchase_receipt = make_purchase_receipt(purchase_order.name)
		purchase_receipt.insert()
		purchase_receipt.submit()

		pending_purchase_invoice = get_pending_purchase_invoice(
			supplier = purchase_order.supplier,
			amount = purchase_receipt.net_total + 499,
			purchase_order = purchase_order.name
		)

		pending_purchase_invoice.insert(ignore_permissions=True, ignore_mandatory=True)

		self.assertEqual(len(pending_purchase_invoice.items), 1)
		self.assertIn(purchase_receipt.name, [r.reference_docname for r in pending_purchase_invoice.items])
		self.assertEqual(pending_purchase_invoice.status, "Ready")

		settings: eTransactionsSettings = frappe.get_single("eTransactions Settings") # type: ignore
		settings.max_difference_amount = 500.0
		settings.max_difference_percentage_on_net_total = 10.0
		settings.save()

		pending_purchase_invoice.reload()
		pending_purchase_invoice.items[0].rate = purchase_receipt.net_total + 499
		pending_purchase_invoice.save()
		time.sleep(5) # Todo: wait for commit correctly
		pending_purchase_invoice.reload()
		self.assertEqual(pending_purchase_invoice.status, "Completed")

		frappe.db.set_single_value("eTransactions Settings", "max_difference_amount", 0)
		frappe.db.set_single_value("eTransactions Settings", "max_difference_percentage_on_net_total", 0)

	@change_settings(
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	def test_auto_reconciliation_03(self):
		"""
		Purchase order is received
		Supplier invoice is higher than purchase order. An allowance is set, below the invoice amount.
		"""
		purchase_order = get_purchase_order(
			company=get_default_company(),
			item_code=choice(self.items), # type: ignore
			qty=10,
			rate=500
		) # type: ignore
		purchase_order.insert()
		purchase_order.submit()

		purchase_receipt = make_purchase_receipt(purchase_order.name)
		purchase_receipt.insert()
		purchase_receipt.submit()

		pending_purchase_invoice = get_pending_purchase_invoice(
			supplier = purchase_order.supplier,
			amount = purchase_receipt.net_total + 499,
			purchase_order = purchase_order.name
		)

		pending_purchase_invoice.insert(ignore_permissions=True, ignore_mandatory=True)

		self.assertEqual(len(pending_purchase_invoice.items), 1)
		self.assertIn(purchase_receipt.name, [r.reference_docname for r in pending_purchase_invoice.items])
		self.assertEqual(pending_purchase_invoice.status, "Ready")

		frappe.db.set_single_value("eTransactions Settings", "max_difference_amount", 250)
		frappe.db.set_single_value("eTransactions Settings", "max_difference_percentage_on_net_total", 5)

		pending_purchase_invoice.save()
		self.assertEqual(pending_purchase_invoice.status, "Ready")

		frappe.db.set_single_value("eTransactions Settings", "max_difference_amount", 0)
		frappe.db.set_single_value("eTransactions Settings", "max_difference_percentage_on_net_total", 0)


	@change_settings(
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	def test_auto_reconciliation_04(self):
		"""
		Purchase order is received with two PR
		Purchase receipts total amount and supplier invoice match perfectly
		"""
		purchase_order = get_purchase_order(
			company=get_default_company(),
			item_code=choice(self.items), # type: ignore
			qty=10,
			rate=500
		) # type: ignore
		purchase_order.insert()
		purchase_order.submit()

		purchase_receipt_1 = make_purchase_receipt(purchase_order.name)
		for item in purchase_receipt_1.items:
			item.qty = 5
		purchase_receipt_1.insert()
		purchase_receipt_1.submit()

		purchase_receipt_2 = make_purchase_receipt(purchase_order.name)
		purchase_receipt_2.insert()
		purchase_receipt_2.submit()

		pending_purchase_invoice = get_pending_purchase_invoice(
			supplier = purchase_order.supplier,
			amount = purchase_order.net_total,
			purchase_order = purchase_order.name
		)

		pending_purchase_invoice.insert(ignore_permissions=True, ignore_mandatory=True)

		self.assertEqual(len(pending_purchase_invoice.items), 2)
		self.assertIn(purchase_receipt_1.name, [r.reference_docname for r in pending_purchase_invoice.items])
		self.assertIn(purchase_receipt_2.name, [r.reference_docname for r in pending_purchase_invoice.items])

		pending_purchase_invoice.reload()
		self.assertEqual(pending_purchase_invoice.status, "Completed")


def get_purchase_order(company, item_code, qty, rate, **kwargs):
	po: PurchaseOrder = frappe.new_doc("Purchase Order") # type: ignore
	po.company = company or get_default_company() # type: ignore
	po.supplier = get_random("Supplier") # type: ignore
	po.schedule_date = nowdate()

	po.append("items", {
		"item_code": item_code or get_random("Item", filters={"has_variants": False, "is_stock_item": 0}),
		"qty": qty or 1,
		"rate": rate or 500
	})

	if kwargs:
		po.update(kwargs)

	return po

def get_pending_purchase_invoice(supplier, amount, purchase_order):
	pending_invoice: SupplierInvoice = frappe.new_doc("Supplier Invoice") # type: ignore
	pending_invoice.supplier = supplier
	pending_invoice.bill_no = frappe.generate_hash(length=8)
	pending_invoice.bill_date = nowdate()
	pending_invoice.due_date = add_days(nowdate(), 30)
	pending_invoice.supplier_net_amount = flt(amount)
	pending_invoice.supplier_tax_amount = flt(amount) * 0.2
	pending_invoice.supplier_grand_total = flt(amount) * 1.2
	pending_invoice.purchase_order_number = purchase_order
	pending_invoice.flags.ignore_links = True
	return pending_invoice