# Copyright (c) 2024, Dokos SAS and Contributors
# See license.txt


from typing import TYPE_CHECKING
from frappe.tests import IntegrationTestCase, change_settings
import frappe
from frappe.utils import add_days, flt
from frappe.utils.data import nowdate

from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice

if TYPE_CHECKING:
	from ocr.ocr.doctype.pending_purchase_invoice.pending_purchase_invoice import PendingPurchaseInvoice

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
		"OCR Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
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
		"OCR Settings",
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
			"supplier_net_amount": 500,
			"bill_no": "CN-123",
			"bill_date": nowdate(),
			"items": [{
				"item_code": "_Test Item",
				"qty": -1,
				"rate": 500,
				"amount": -500,
				"expense_account": self.EXPENSE_ACCOUNT,
			}],
			"credit_note_allocations": [{"purchase_invoice": pi.name, "allocated_amount": 500}],
		}) # type: ignore
		credit_note_ppi.insert()

		cn_name = frappe.db.get_value("Purchase Invoice", {"pending_purchase_invoice": credit_note_ppi.name})
		self.assertTrue(cn_name)
		cn = frappe.get_doc("Purchase Invoice", cn_name) # type: ignore
		self.assertEqual(cn.is_return, 1) # type: ignore
		self.assertFalse(cn.return_against) # type: ignore
		self.assertEqual(cn.update_outstanding_for_self, 1) # type: ignore

		pi.reload()
		self.assertEqual(flt(pi.outstanding_amount), 4500)  # 5000 - 500 reconciled

	# --- Multi-invoice credit note allocation -------------------------------

	EXPENSE_ACCOUNT = "_Test Account Cost for Goods Sold - _TC"

	def _make_submitted_invoice(self, rate, posting_date=None, submit=True):
		return make_purchase_invoice(
			supplier=self.supplier.name,
			company=self.company,
			currency="INR",
			qty=1,
			rate=rate,
			expense_account=self.EXPENSE_ACCOUNT,
			posting_date=posting_date or nowdate(),
			do_not_submit=not submit,
		)

	def _make_credit_note(self, amount, allocations=None, insert=True):
		doc = frappe.get_doc({
			"doctype": "Pending Purchase Invoice",
			"supplier": self.supplier.name,
			"company": self.company,
			"currency": "INR",
			"is_return": 1,
			"supplier_net_amount": amount,
			"bill_no": frappe.generate_hash(length=8),
			"bill_date": nowdate(),
			# Credit note lines carry negative quantities so the invoice holds a credit
			# balance that can be reconciled against the allocated invoices.
			"items": [{
				"item_code": "_Test Item",
				"qty": -1,
				"rate": amount,
				"amount": -amount,
				"expense_account": self.EXPENSE_ACCOUNT,
			}],
			"credit_note_allocations": [
				{"purchase_invoice": a[0], "allocated_amount": a[1]} for a in (allocations or [])
			],
		})
		if insert:
			doc.insert()
		return doc

	@change_settings(
		"OCR Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	@change_settings("Accounts Settings", {"mandatory_accounting_journal": 0})
	def test_credit_note_allocated_to_multiple_invoices(self):
		pi_a = self._make_submitted_invoice(5000)
		pi_b = self._make_submitted_invoice(3000)

		credit_note = self._make_credit_note(4000, allocations=[(pi_a.name, 3000), (pi_b.name, 1000)])

		cn_name = frappe.db.get_value("Purchase Invoice", {"pending_purchase_invoice": credit_note.name})
		self.assertTrue(cn_name)
		cn = frappe.get_doc("Purchase Invoice", cn_name) # type: ignore
		self.assertEqual(cn.is_return, 1) # type: ignore
		self.assertFalse(cn.return_against) # type: ignore
		self.assertEqual(cn.update_outstanding_for_self, 1) # type: ignore

		pi_a.reload()
		pi_b.reload()
		self.assertEqual(flt(pi_a.outstanding_amount), 2000)
		self.assertEqual(flt(pi_b.outstanding_amount), 2000)

	def test_credit_note_fifo_prefill(self):
		pi1 = self._make_submitted_invoice(2000, posting_date=add_days(nowdate(), -10))
		pi2 = self._make_submitted_invoice(2000, posting_date=add_days(nowdate(), -5))
		self._make_submitted_invoice(2000, posting_date=add_days(nowdate(), -1))

		credit_note = self._make_credit_note(3000)
		rows = credit_note.allocate_credit_note_fifo()

		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["purchase_invoice"], pi1.name)
		self.assertEqual(flt(rows[0]["allocated_amount"]), 2000)
		self.assertEqual(rows[1]["purchase_invoice"], pi2.name)
		self.assertEqual(flt(rows[1]["allocated_amount"]), 1000)

	@change_settings(
		"OCR Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	@change_settings("Accounts Settings", {"mandatory_accounting_journal": 0})
	def test_credit_note_allocation_skips_draft_invoice(self):
		pi_sub = self._make_submitted_invoice(5000)
		pi_draft = self._make_submitted_invoice(3000, submit=False)

		credit_note = self._make_credit_note(3000, allocations=[(pi_sub.name, 2000), (pi_draft.name, 1000)])

		cn_name = frappe.db.get_value("Purchase Invoice", {"pending_purchase_invoice": credit_note.name})
		cn = frappe.get_doc("Purchase Invoice", cn_name) # type: ignore

		pi_sub.reload()
		self.assertEqual(flt(pi_sub.outstanding_amount), 3000)  # 5000 - 2000 reconciled
		# Draft skipped: only 2000 of the 3000 credit was allocated.
		self.assertEqual(flt(cn.outstanding_amount), -1000)

	def test_credit_note_over_allocation_rejected(self):
		pi_a = self._make_submitted_invoice(1000)
		credit_note = self._make_credit_note(5000, allocations=[(pi_a.name, 5000)], insert=False)
		self.assertRaises(frappe.ValidationError, credit_note.insert)
