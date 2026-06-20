# Copyright (c) 2024, Dokos SAS and Contributors
# See license.txt


from typing import TYPE_CHECKING
from etransactions.tests.utils import eTransactionsTestSuite
from frappe.tests.utils import change_settings
import frappe
from frappe.utils.data import nowdate

from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
from erpnext.buying.doctype.purchase_order.mapper import make_purchase_receipt

if TYPE_CHECKING:
	from etransactions.etransactions.doctype.supplier_invoice.supplier_invoice import SupplierInvoice

IGNORE_TEST_RECORD_DEPENDENCIES = ["Supplier", "Company", "Currency", "Tax Category", "Purchase Taxes and Charges Template", "Purchase Invoice", "File", "OCR Request", "Item", "Cost Center", "Project"]

class TestSupplierInvoice(eTransactionsTestSuite):
	def setUp(self):
		self.clear_existing_data()
		self.create_prerequisites()

	def tearDown(self):
		frappe.db.rollback()

	def create_prerequisites(self):
		self.supplier = create_supplier()
		create_item()
		self.company = "_Test Company"


	def clear_existing_data(self):
		for doctype in ["Purchase Invoice", "Supplier Invoice", "Purchase Receipt", "Purchase Order"]:
			frappe.db.delete(doctype)


	@change_settings(
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	@change_settings("Accounts Settings", {"mandatory_accounting_journal": 0})
	def test_auto_reconciliation_with_purchase_receipt(self):
		po = create_purchase_order(supplier=self.supplier.name, company=self.company, qty=1.0, rate=5000, warehouse="_Test Warehouse - _TC")
		pr = make_purchase_receipt(po.name)
		pr.submit()

		ppi = frappe.get_doc({
			"doctype": "Supplier Invoice",
			"supplier": po.supplier,
			"company": po.company,
			"purchase_order_number": po.name,
			"supplier_net_amount": pr.net_total,
			"bill_no": "123",
			"bill_date": nowdate(),
		})
		ppi.insert()

		pi_name = frappe.db.get_value("Purchase Invoice", {"supplier_invoice": ppi.name})
		self.assertTrue(pi_name)
		pi = frappe.get_doc("Purchase Invoice", pi_name) # type: ignore
		self.assertEqual(pi.total, 5000.0) # type: ignore

	@change_settings(
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	@change_settings("Accounts Settings", {"mandatory_accounting_journal": 0})
	def test_auto_reconciliation_of_credit_note(self):
		po = create_purchase_order(supplier=self.supplier.name, company=self.company, qty=1.0, rate=5000, warehouse="_Test Warehouse - _TC")
		pr = make_purchase_receipt(po.name)
		pr.submit()

		ppi: SupplierInvoice = frappe.get_doc({
			"doctype": "Supplier Invoice",
			"supplier": po.supplier,
			"company": po.company,
			"purchase_order_number": po.name,
			"supplier_net_amount": pr.net_total,
			"bill_no": "123",
			"bill_date": nowdate(),
		}) # type: ignore
		ppi.insert()

		pi_name = frappe.db.get_value("Purchase Invoice", {"supplier_invoice": ppi.name})
		pi = frappe.get_doc("Purchase Invoice", pi_name) # type: ignore

		credit_note_ppi: SupplierInvoice = frappe.get_doc({
			"doctype": "Supplier Invoice",
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

		cn_name = frappe.db.get_value("Purchase Invoice", {"supplier_invoice": credit_note_ppi.name})
		self.assertTrue(cn_name)
		cn = frappe.get_doc("Purchase Invoice", cn_name) # type: ignore
		self.assertEqual(cn.is_return, 1) # type: ignore
		self.assertEqual(cn.return_against, pi.name) # type: ignore


	def _new_supplier(self, name, tax_id=None):
		supplier = frappe.new_doc("Supplier")
		supplier.supplier_name = name
		supplier.supplier_group = "Services"
		if tax_id:
			supplier.tax_id = tax_id
		supplier.insert(ignore_if_duplicate=True)
		return supplier

	def _supplier_invoice_stub(self, supplier, tax_id):
		doc = frappe.new_doc("Supplier Invoice")
		doc.supplier = supplier
		doc.tax_id = tax_id
		return doc

	def test_supplier_tax_id_learned_when_unique(self):
		suffix = frappe.generate_hash(length=6).upper()
		new_tax_id = f"FR{suffix}LEARN"
		supplier = self._new_supplier(f"Learner {suffix}")

		self._supplier_invoice_stub(supplier.name, new_tax_id)._maybe_update_supplier_tax_id()

		self.assertEqual(
			frappe.db.get_value("Supplier", supplier.name, "tax_id"), new_tax_id
		)

	def test_supplier_tax_id_not_overwritten_when_duplicate(self):
		suffix = frappe.generate_hash(length=6).upper()
		shared = f"FR{suffix}DUP"
		self._new_supplier(f"Holder {suffix}", tax_id=shared)
		target = self._new_supplier(f"Target {suffix}")

		self._supplier_invoice_stub(target.name, shared)._maybe_update_supplier_tax_id()

		self.assertFalse(frappe.db.get_value("Supplier", target.name, "tax_id"))

	def test_supplier_tax_id_not_set_to_company_vat(self):
		suffix = frappe.generate_hash(length=6).upper()
		buyer_vat = f"FR{suffix}BUYER"
		original = frappe.db.get_value("Company", self.company, "tax_id")
		frappe.db.set_value("Company", self.company, "tax_id", buyer_vat)
		try:
			target = self._new_supplier(f"Buyer VAT Target {suffix}")

			self._supplier_invoice_stub(target.name, buyer_vat)._maybe_update_supplier_tax_id()

			self.assertFalse(frappe.db.get_value("Supplier", target.name, "tax_id"))
		finally:
			frappe.db.set_value("Company", self.company, "tax_id", original)


def create_supplier():
	supplier = frappe.new_doc("Supplier")
	supplier.supplier_name = "_Test Supplier"
	supplier.supplier_group = "Services"
	supplier.insert(ignore_if_duplicate=True)

	return supplier

def create_item():
	item = frappe.new_doc("Item")
	item.item_name = "_Test Item"
	item.item_code = "_Test Item"
	item.item_group = "All Item Groups"
	item.insert(ignore_if_duplicate=True)

	return item