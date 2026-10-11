# Copyright (c) 2024, Dokos SAS and Contributors
# See license.txt


from typing import TYPE_CHECKING

import frappe
from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice
from erpnext.buying.doctype.purchase_order.mapper import make_purchase_receipt
from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
from frappe.tests.utils import change_settings
from frappe.utils import add_days, flt, getdate
from frappe.utils.data import nowdate

from etransactions.tests.utils import eTransactionsTestSuite

if TYPE_CHECKING:
	from etransactions.etransactions.doctype.supplier_invoice.supplier_invoice import SupplierInvoice

IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Supplier",
	"Company",
	"Currency",
	"Tax Category",
	"Purchase Taxes and Charges Template",
	"Purchase Invoice",
	"File",
	"OCR Request",
	"Item",
	"Cost Center",
	"Project",
]


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
		po = create_purchase_order(
			supplier=self.supplier.name,
			company=self.company,
			qty=1.0,
			rate=5000,
			warehouse="_Test Warehouse - _TC",
		)
		pr = make_purchase_receipt(po.name)
		pr.submit()

		ppi = frappe.get_doc(
			{
				"doctype": "Supplier Invoice",
				"supplier": po.supplier,
				"company": po.company,
				"purchase_order_number": po.name,
				"supplier_net_amount": pr.net_total,
				"bill_no": "123",
				"bill_date": nowdate(),
			}
		)
		ppi.insert()

		pi_name = frappe.db.get_value("Purchase Invoice", {"supplier_invoice": ppi.name})
		self.assertTrue(pi_name)
		pi = frappe.get_doc("Purchase Invoice", pi_name)  # type: ignore
		self.assertEqual(pi.total, 5000.0)  # type: ignore

	@change_settings(
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	@change_settings("Accounts Settings", {"mandatory_accounting_journal": 0})
	def test_auto_reconciliation_of_credit_note(self):
		po = create_purchase_order(
			supplier=self.supplier.name,
			company=self.company,
			qty=1.0,
			rate=5000,
			warehouse="_Test Warehouse - _TC",
		)
		pr = make_purchase_receipt(po.name)
		pr.submit()

		ppi: SupplierInvoice = frappe.get_doc(
			{
				"doctype": "Supplier Invoice",
				"supplier": po.supplier,
				"company": po.company,
				"purchase_order_number": po.name,
				"supplier_net_amount": pr.net_total,
				"bill_no": "123",
				"bill_date": nowdate(),
			}
		)  # type: ignore
		ppi.insert()

		pi_name = frappe.db.get_value("Purchase Invoice", {"supplier_invoice": ppi.name})
		pi = frappe.get_doc("Purchase Invoice", pi_name)  # type: ignore

		credit_note_ppi: SupplierInvoice = frappe.get_doc(
			{
				"doctype": "Supplier Invoice",
				"supplier": po.supplier,
				"company": po.company,
				"is_return": 1,
				"supplier_net_amount": 500,
				"bill_no": "CN-123",
				"bill_date": nowdate(),
				"items": [
					{
						"item_code": "_Test Item",
						"qty": -1,
						"rate": 500,
						"amount": -500,
						"expense_account": self.EXPENSE_ACCOUNT,
					}
				],
				"credit_note_allocations": [{"purchase_invoice": pi.name, "allocated_amount": 500}],
			}
		)  # type: ignore
		credit_note_ppi.insert()

		cn_name = frappe.db.get_value("Purchase Invoice", {"supplier_invoice": credit_note_ppi.name})
		self.assertTrue(cn_name)
		cn = frappe.get_doc("Purchase Invoice", cn_name)  # type: ignore
		self.assertEqual(cn.is_return, 1)  # type: ignore
		self.assertFalse(cn.return_against)  # type: ignore
		self.assertEqual(cn.update_outstanding_for_self, 1)  # type: ignore

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
		doc = frappe.get_doc(
			{
				"doctype": "Supplier Invoice",
				"supplier": self.supplier.name,
				"company": self.company,
				"currency": "INR",
				"is_return": 1,
				"supplier_net_amount": amount,
				"bill_no": frappe.generate_hash(length=8),
				"bill_date": nowdate(),
				# Credit note lines carry negative quantities so the invoice holds a credit
				# balance that can be reconciled against the allocated invoices.
				"items": [
					{
						"item_code": "_Test Item",
						"qty": -1,
						"rate": amount,
						"amount": -amount,
						"expense_account": self.EXPENSE_ACCOUNT,
					}
				],
				"credit_note_allocations": [
					{"purchase_invoice": a[0], "allocated_amount": a[1]} for a in (allocations or [])
				],
			}
		)
		if insert:
			doc.insert()
		return doc

	@change_settings(
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	@change_settings("Accounts Settings", {"mandatory_accounting_journal": 0})
	def test_credit_note_allocated_to_multiple_invoices(self):
		pi_a = self._make_submitted_invoice(5000)
		pi_b = self._make_submitted_invoice(3000)

		credit_note = self._make_credit_note(4000, allocations=[(pi_a.name, 3000), (pi_b.name, 1000)])

		cn_name = frappe.db.get_value("Purchase Invoice", {"supplier_invoice": credit_note.name})
		self.assertTrue(cn_name)
		cn = frappe.get_doc("Purchase Invoice", cn_name)  # type: ignore
		self.assertEqual(cn.is_return, 1)  # type: ignore
		self.assertFalse(cn.return_against)  # type: ignore
		self.assertEqual(cn.update_outstanding_for_self, 1)  # type: ignore

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
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	@change_settings("Accounts Settings", {"mandatory_accounting_journal": 0})
	def test_credit_note_allocation_skips_draft_invoice(self):
		pi_sub = self._make_submitted_invoice(5000)
		pi_draft = self._make_submitted_invoice(3000, submit=False)

		credit_note = self._make_credit_note(3000, allocations=[(pi_sub.name, 2000), (pi_draft.name, 1000)])

		cn_name = frappe.db.get_value("Purchase Invoice", {"supplier_invoice": credit_note.name})
		cn = frappe.get_doc("Purchase Invoice", cn_name)  # type: ignore

		pi_sub.reload()
		self.assertEqual(flt(pi_sub.outstanding_amount), 3000)  # 5000 - 2000 reconciled
		# Draft skipped: only 2000 of the 3000 credit was allocated.
		self.assertEqual(flt(cn.outstanding_amount), -1000)

	def test_credit_note_over_allocation_rejected(self):
		pi_a = self._make_submitted_invoice(1000)
		credit_note = self._make_credit_note(5000, allocations=[(pi_a.name, 5000)], insert=False)
		self.assertRaises(frappe.ValidationError, credit_note.insert)

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

	# --- Posting date propagation -------------------------------------------

	def _supplier_invoice_with_posting_date(self, posting_date):
		doc = frappe.get_doc(
			{
				"doctype": "Supplier Invoice",
				"supplier": self.supplier.name,
				"company": self.company,
				"bill_no": frappe.generate_hash(length=8),
				"bill_date": posting_date,
				"posting_date": posting_date,
			}
		)
		doc.insert()
		return doc

	def test_purchase_invoice_mapped_from_order_keeps_supplier_invoice_posting_date(self):
		"""The order-first route must not repost the invoice on the day it was mapped."""
		from erpnext.buying.doctype.purchase_order.mapper import make_purchase_invoice as make_pi_from_po

		posting_date = add_days(nowdate(), -45)
		supplier_invoice = self._supplier_invoice_with_posting_date(posting_date)

		po = create_purchase_order(
			supplier=self.supplier.name,
			company=self.company,
			qty=1.0,
			rate=100,
			warehouse="_Test Warehouse - _TC",
		)
		frappe.db.set_value("Purchase Order", po.name, "supplier_invoice", supplier_invoice.name)

		pi = make_pi_from_po(po.name)

		self.assertEqual(getdate(pi.posting_date), getdate(posting_date))
		# Without this flag `validate_posting_time` rewrites posting_date to now on save.
		self.assertTrue(pi.set_posting_time)

	def test_purchase_invoice_created_from_supplier_invoice_keeps_posting_date(self):
		"""Pin the invoice-first route, which already carried the date correctly."""
		posting_date = add_days(nowdate(), -45)
		supplier_invoice = self._supplier_invoice_with_posting_date(posting_date)
		supplier_invoice.append(
			"items",
			{
				"item_code": "_Test Item",
				"qty": 1,
				"rate": 100,
				"amount": 100,
				"expense_account": self.EXPENSE_ACCOUNT,
			},
		)
		supplier_invoice.save()

		pi = supplier_invoice.get_purchase_invoice(purchase_order_is_mandatory=False)

		self.assertEqual(getdate(pi.posting_date), getdate(posting_date))
		self.assertTrue(pi.set_posting_time)

	# --- E-invoice credit lines ----------------------------------------------

	def test_lines_stating_their_own_amount_survive_total_recalculation(self):
		"""Recalculating the totals used to recompute every line as qty * rate, collapsing
		the lines that state their own amount.

		The quantities vary on purpose: deriving a rate from the amount would round the
		three-unit line and divide by zero on the quantity-less one. One line is positive,
		because a stated amount is not always a credit.
		"""
		invoice = frappe.get_doc(
			{
				"doctype": "Supplier Invoice",
				"supplier": self.supplier.name,
				"company": self.company,
				"bill_no": frappe.generate_hash(length=8),
				"bill_date": nowdate(),
				"posting_date": nowdate(),
				# Declared by the supplier, so the recalculation has an oracle to match.
				"supplier_net_amount": 17.70,
				"items": [
					{
						"item_code": "_Test Item",
						"qty": 1,
						"rate": 12,
						"amount": 12,
						"expense_account": self.EXPENSE_ACCOUNT,
					},
					{
						"item_code": "_Test Item",
						"qty": 2,
						"rate": 3.40,
						"amount": 6.80,
						"expense_account": self.EXPENSE_ACCOUNT,
					},
					{
						"item_code": "_Test Item",
						"qty": 1,
						"rate": 0,
						"amount": -0.30,
						"expense_account": self.EXPENSE_ACCOUNT,
					},
					{
						"item_code": "_Test Item",
						"qty": 3,
						"rate": 0,
						"amount": -1.00,
						"expense_account": self.EXPENSE_ACCOUNT,
					},
					{
						"item_code": "_Test Item",
						"qty": 0,
						"rate": 0,
						"amount": -0.30,
						"expense_account": self.EXPENSE_ACCOUNT,
					},
					{
						"item_code": "_Test Item",
						"qty": 0,
						"rate": 0,
						"amount": 0.50,
						"expense_account": self.EXPENSE_ACCOUNT,
					},
				],
			}
		)
		invoice.insert(ignore_mandatory=True)

		self.assertEqual(flt(invoice.net_total, 2), flt(invoice.supplier_net_amount, 2))

	def _invoice_with_sub_cent_unit_price(self, surcharge_amount=8.46):
		return frappe.get_doc(
			{
				"doctype": "Supplier Invoice",
				"supplier": self.supplier.name,
				"company": self.company,
				"bill_no": frappe.generate_hash(length=8),
				"bill_date": nowdate(),
				"posting_date": nowdate(),
				"supplier_net_amount": 76.83,
				"items": [
					{
						"item_code": "_Test Item",
						"qty": 1,
						"rate": 12,
						"amount": 12,
						"expense_account": self.EXPENSE_ACCOUNT,
					},
					{
						"item_code": "_Test Item",
						"qty": 563.71,
						"rate": 0.1,
						"amount": 56.37,
						"expense_account": self.EXPENSE_ACCOUNT,
					},
					{
						"item_code": "_Test Item",
						"qty": 563.71,
						"rate": 0.015,
						"amount": surcharge_amount,
						"expense_account": self.EXPENSE_ACCOUNT,
					},
				],
			}
		).insert(ignore_mandatory=True)

	def test_sub_cent_unit_price_survives_total_recalculation(self):
		"""A rate of 0.015 was rounded to 0.02 before being multiplied, turning 8.46 into 11.27."""
		invoice = self._invoice_with_sub_cent_unit_price()

		self.assertEqual(flt(invoice.net_total, 2), 76.83)

		pi = invoice.get_purchase_invoice(purchase_order_is_mandatory=False)
		self.assertEqual(flt(pi.net_total, 2), 76.83)

	def test_sub_cent_unit_price_with_stale_amount_is_recomputed(self):
		"""An amount that no longer matches qty * rate is not trusted over the rate."""
		invoice = self._invoice_with_sub_cent_unit_price(surcharge_amount=5)

		# 12 + 56.37 + 563.71 * 0.02
		self.assertEqual(flt(invoice.net_total, 2), 79.64)

	@change_settings(
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	@change_settings("Accounts Settings", {"mandatory_accounting_journal": 0})
	def test_invoice_carrying_a_credit_line_is_not_reconciled_automatically(self):
		"""Now that the totals agree with the supplier, nothing else stops this invoice from
		booking a purchase invoice that cannot hold the credit.

		The ordered item doubles as a regression guard: it has a purchase history, which
		`set_missing_values` would price the credit line from if it were still zero-rate.
		"""
		po = create_purchase_order(
			supplier=self.supplier.name,
			company=self.company,
			qty=1.0,
			rate=5000,
			warehouse="_Test Warehouse - _TC",
		)
		pr = make_purchase_receipt(po.name)
		pr.submit()

		invoice = frappe.get_doc(
			{
				"doctype": "Supplier Invoice",
				"supplier": po.supplier,
				"company": po.company,
				"purchase_order_number": po.name,
				"supplier_net_amount": flt(pr.net_total) - 1,
				"bill_no": frappe.generate_hash(length=8),
				"bill_date": nowdate(),
				"items": [
					{
						"item_code": pr.items[0].item_code,
						"qty": 1,
						"rate": pr.net_total,
						"amount": pr.net_total,
						"expense_account": self.EXPENSE_ACCOUNT,
						"reference_doctype": "Purchase Receipt",
						"reference_docname": pr.name,
						"row": pr.items[0].name,
					},
					{
						"item_code": "_Test Item",
						"qty": 1,
						"rate": 0,
						"amount": -1.00,
						"expense_account": self.EXPENSE_ACCOUNT,
					},
				],
			}
		)
		invoice.insert(ignore_mandatory=True)

		self.assertEqual(flt(invoice.net_total), flt(invoice.supplier_net_amount))
		self.assertFalse(frappe.db.exists("Purchase Invoice", {"supplier_invoice": invoice.name}))

	# --- Item line prefill ---------------------------------------------------

	def _captured_invoice(self, supplier=None, net_amount=100, ocr_request=None, bill_date=None):
		doc = frappe.new_doc("Supplier Invoice")
		doc.supplier = supplier or self.supplier.name
		doc.company = self.company
		doc.posting_date = nowdate()
		doc.bill_date = bill_date
		doc.bill_no = frappe.generate_hash(length=8)
		doc.supplier_net_amount = net_amount
		doc.ocr_request = ocr_request
		doc.insert(ignore_mandatory=True)
		return doc

	def test_items_prefilled_from_the_suppliers_last_invoice(self):
		"""The single-line suppliers that dominate captured invoices become zero-touch."""
		previous = self._make_submitted_invoice(1000)

		invoice = self._captured_invoice(net_amount=250)

		self.assertEqual(len(invoice.items), 1)
		self.assertEqual(invoice.items[0].item_code, previous.items[0].item_code)
		self.assertEqual(invoice.items[0].expense_account, previous.items[0].expense_account)
		# The amount comes from the invoice being captured, not from the previous one.
		self.assertEqual(flt(invoice.items[0].rate), 250)

	def test_items_prefilled_from_the_supplier_item_mapping(self):
		alias = frappe.new_doc("eTransactions Supplier Item Alias")
		alias.supplier = self.supplier.name
		alias.supplier_item_code = "Abonnement Fibre Pro"
		alias.item_code = "_Test Item"
		alias.expense_account = self.EXPENSE_ACCOUNT
		alias.insert()

		ocr_request = frappe.new_doc("OCR Request")
		ocr_request.name = frappe.generate_hash(length=10)
		ocr_request.analysis = frappe.as_json(
			{"_children": [{"ITEM": "Abonnement Fibre Pro 39,90 EUR", "PRICE": "39.90", "QUANTITY": "1"}]}
		)
		ocr_request.db_insert()

		invoice = self._captured_invoice(ocr_request=ocr_request.name)

		self.assertEqual(len(invoice.items), 1)
		self.assertEqual(invoice.items[0].item_code, "_Test Item")
		self.assertEqual(invoice.items[0].expense_account, self.EXPENSE_ACCOUNT)
		self.assertEqual(flt(invoice.items[0].rate), 39.90)

	def test_no_prefill_for_a_supplier_with_no_history(self):
		newcomer = self._new_supplier(f"Newcomer {frappe.generate_hash(length=6)}")

		invoice = self._captured_invoice(supplier=newcomer.name)

		self.assertFalse(invoice.items)

	def test_no_prefill_when_the_setting_is_off(self):
		self._make_submitted_invoice(1000)
		frappe.db.set_single_value("eTransactions Settings", "prefill_invoice_items", 0)

		invoice = self._captured_invoice()

		self.assertFalse(invoice.items)

	def test_no_prefill_without_a_captured_amount(self):
		self._make_submitted_invoice(1000)

		invoice = self._captured_invoice(net_amount=0)

		self.assertFalse(invoice.items)

	# --- Purchase order matching ---------------------------------------------

	def _open_order(self, rate, transaction_date=None):
		return create_purchase_order(
			supplier=self.supplier.name,
			company=self.company,
			qty=1,
			rate=rate,
			warehouse="_Test Warehouse - _TC",
			transaction_date=transaction_date,
		)

	def _ocr_request(self, *expense_rows):
		ocr_request = frappe.new_doc("OCR Request")
		ocr_request.name = frappe.generate_hash(length=10)
		ocr_request.analysis = frappe.as_json({"_children": [{"EXPENSE_ROW": row} for row in expense_rows]})
		ocr_request.db_insert()
		return ocr_request.name

	@staticmethod
	def _linked_orders(invoice):
		return {row.reference_docname for row in invoice.items if row.reference_doctype == "Purchase Order"}

	def test_cites_reference_ignores_blank_references(self):
		from etransactions.etransactions.doctype.supplier_invoice.supplier_invoice import cites_reference

		self.assertFalse(cites_reference("Installation 2,00 h 45,00", None, "", "  "))
		self.assertTrue(cites_reference("Votre ref. : PO-0042 48.50", "", "PO-0042"))
		self.assertFalse(cites_reference("Votre ref. : PO-00421", "PO-0042"))

	@change_settings("eTransactions Settings", {"prefill_invoice_items": 0})
	def test_orders_without_confirmation_number_not_matched_by_every_ocr_line(self):
		"""Regression: a blank confirmation number used to match any OCR line, so every open order was linked."""
		self._open_order(5)
		self._open_order(48.50)
		ocr_request = self._ocr_request("Installation 2,00 h 45,00 0% 90,00", "Livraison 12,00")

		invoice = self._captured_invoice(net_amount=102, ocr_request=ocr_request)

		self.assertFalse(self._linked_orders(invoice))

	@change_settings("eTransactions Settings", {"prefill_invoice_items": 0})
	def test_order_cited_on_an_ocr_line_is_linked(self):
		cited = self._open_order(48.50)
		self._open_order(5)
		ocr_request = self._ocr_request(f"Votre ref. : {cited.name} 48.50 1")

		invoice = self._captured_invoice(net_amount=48.50, ocr_request=ocr_request)

		self.assertEqual(self._linked_orders(invoice), {cited.name})

	@change_settings("eTransactions Settings", {"prefill_invoice_items": 0})
	def test_only_open_order_linked_by_default(self):
		order = self._open_order(150)

		invoice = self._captured_invoice(net_amount=240)

		self.assertEqual(self._linked_orders(invoice), {order.name})

	@change_settings(
		"eTransactions Settings", {"prefill_invoice_items": 0, "no_single_purchase_order_match": 1}
	)
	def test_only_open_order_not_linked_when_the_setting_is_on(self):
		self._open_order(150)

		invoice = self._captured_invoice(net_amount=240)

		self.assertFalse(self._linked_orders(invoice))

	@change_settings(
		"eTransactions Settings", {"prefill_invoice_items": 0, "no_single_purchase_order_match": 1}
	)
	def test_order_with_the_same_amount_linked_only_if_placed_before_the_invoice(self):
		order = self._open_order(100, transaction_date=add_days(nowdate(), -5))

		before = self._captured_invoice(net_amount=100, bill_date=add_days(nowdate(), -10))
		after = self._captured_invoice(net_amount=100, bill_date=nowdate())

		self.assertFalse(self._linked_orders(before))
		self.assertEqual(self._linked_orders(after), {order.name})

	@change_settings("eTransactions Settings", {"prefill_invoice_items": 0})
	def test_order_already_on_another_open_invoice_is_not_linked_again(self):
		order = self._open_order(48.50)
		self._open_order(5)

		first = self._captured_invoice(
			net_amount=48.50, ocr_request=self._ocr_request(f"Votre ref. : {order.name} 48.50 1")
		)
		second = self._captured_invoice(
			net_amount=48.50, ocr_request=self._ocr_request(f"Votre ref. : {order.name} 48.50 1")
		)

		self.assertEqual(self._linked_orders(first), {order.name})
		self.assertFalse(self._linked_orders(second))

	@change_settings("eTransactions Settings", {"prefill_invoice_items": 0})
	def test_order_on_a_closed_invoice_can_be_linked_again(self):
		order = self._open_order(48.50)
		self._open_order(5)
		first = self._captured_invoice(
			net_amount=48.50, ocr_request=self._ocr_request(f"Votre ref. : {order.name} 48.50 1")
		)
		first.db_set("status", "Closed")

		second = self._captured_invoice(
			net_amount=48.50, ocr_request=self._ocr_request(f"Votre ref. : {order.name} 48.50 1")
		)

		self.assertEqual(self._linked_orders(second), {order.name})

	@change_settings("eTransactions Settings", {"prefill_invoice_items": 0})
	def test_deleted_suggested_lines_are_not_put_back_on_save(self):
		self._open_order(150)
		invoice = self._captured_invoice(net_amount=240)
		self.assertTrue(invoice.items)

		invoice.set("items", [])
		invoice.save()

		self.assertFalse(invoice.items)

	def test_supplier_item_mapping_learned_from_a_confirmed_line(self):
		invoice = frappe.new_doc("Supplier Invoice")
		invoice.supplier = self.supplier.name
		invoice.company = self.company
		invoice.posting_date = nowdate()
		invoice.append(
			"items",
			{
				"item_code": "_Test Item",
				"qty": 1,
				"rate": 42,
				"expense_account": self.EXPENSE_ACCOUNT,
				"supplier_description": "Forfait mensuel 42,00 EUR",
			},
		)
		invoice.insert(ignore_mandatory=True)

		alias = frappe.get_all(
			"eTransactions Supplier Item Alias",
			filters={"supplier": self.supplier.name, "supplier_item_code": "forfait mensuel"},
			fields=["item_code", "expense_account"],
		)
		self.assertEqual(len(alias), 1)
		self.assertEqual(alias[0].item_code, "_Test Item")
		self.assertEqual(alias[0].expense_account, self.EXPENSE_ACCOUNT)

	# --- Buyer company -------------------------------------------------------

	def _invoice_without_company(self, analysis):
		ocr_request = frappe.new_doc("OCR Request")
		ocr_request.name = frappe.generate_hash(length=10)
		ocr_request.analysis = frappe.as_json(analysis)
		ocr_request.db_insert()
		invoice = self._captured_invoice(ocr_request=ocr_request.name)
		# insert() fills an empty company from the defaults
		invoice.db_set("company", None)
		invoice.reload()
		return invoice

	def test_company_matched_again_while_empty(self):
		invoice = self._invoice_without_company({"RECEIVER_NAME": self.company.upper()})

		invoice.save()

		self.assertEqual(invoice.company, self.company)

	def test_receiver_name_learned_from_a_chosen_company(self):
		receiver_name = f"TC Buyer Block {frappe.generate_hash(length=6)}"
		invoice = self._invoice_without_company({"RECEIVER_NAME": receiver_name})

		invoice.company = self.company
		invoice.save()

		self.assertEqual(
			frappe.get_all(
				"eTransactions Company Name Alias", filters={"receiver_name": receiver_name}, pluck="company"
			),
			[self.company],
		)

	def test_patch_gives_a_company_to_ocr_invoices_without_one(self):
		from etransactions.patches import resolve_ocr_supplier_invoice_company

		invoice = self._invoice_without_company(
			{"RECEIVER_ADDRESS": f"{self.company.upper()}\nrue des Lilas"}
		)

		resolve_ocr_supplier_invoice_company.execute()

		self.assertEqual(frappe.db.get_value("Supplier Invoice", invoice.name, "company"), self.company)

	# --- Vendor name alias learning -----------------------------------------

	def _ocr_request_with_vendor_name(self, vendor_name):
		# Written straight to the table: `after_insert` would call out to the OCR service
		# and, finding no file, roll the transaction back.
		ocr_request = frappe.new_doc("OCR Request")
		ocr_request.name = frappe.generate_hash(length=10)
		ocr_request.analysis = frappe.as_json({"VENDOR_NAME": vendor_name})
		ocr_request.db_insert()
		return ocr_request

	def _learn_alias_from(self, vendor_name, supplier=None):
		doc = frappe.new_doc("Supplier Invoice")
		doc.supplier = supplier or self.supplier.name
		doc.supplier_name = doc.supplier
		doc.ocr_request = self._ocr_request_with_vendor_name(vendor_name).name
		doc._learn_from_manual_match()
		return doc

	def _alias_exists(self, vendor_name):
		return bool(frappe.db.exists("eTransactions Supplier Name Alias", {"vendor_name": vendor_name}))

	def test_alias_learned_from_a_real_vendor_name(self):
		vendor_name = f"Vendor Block {frappe.generate_hash(length=6)}"

		self._learn_alias_from(vendor_name)

		self.assertTrue(self._alias_exists(vendor_name))

	def test_alias_not_learned_from_buyer_company_name(self):
		"""OCR reading our own letterhead as the vendor is what poisoned the table."""
		company_name = frappe.db.get_value("Company", self.company, "company_name")
		vendor_name = f"{company_name} SAS"

		self._learn_alias_from(vendor_name)

		self.assertFalse(self._alias_exists(vendor_name))

	def test_alias_not_learned_when_claimed_by_another_supplier(self):
		vendor_name = f"Contested Block {frappe.generate_hash(length=6)}"
		other = self._new_supplier(f"Other Claimant {frappe.generate_hash(length=6)}")
		self._learn_alias_from(vendor_name, supplier=other.name)

		self._learn_alias_from(vendor_name)

		self.assertEqual(
			frappe.get_all(
				"eTransactions Supplier Name Alias",
				filters={"vendor_name": vendor_name},
				pluck="supplier",
			),
			[other.name],
		)

	def test_retry_supplier_match_does_not_learn_an_alias(self):
		"""A bulk re-match is a guess; only a human correction may become an alias."""
		from etransactions.etransactions.doctype.supplier_invoice.supplier_invoice import (
			retry_supplier_match,
		)

		suffix = frappe.generate_hash(length=6)
		target = self._new_supplier(f"Retry Target {suffix}")
		ocr_request = self._ocr_request_with_vendor_name(target.supplier_name)

		invoice = frappe.new_doc("Supplier Invoice")
		invoice.supplier = self.supplier.name
		invoice.company = self.company
		invoice.posting_date = nowdate()
		invoice.ocr_request = ocr_request.name
		invoice.insert(ignore_mandatory=True)

		retry_supplier_match([invoice.name])

		invoice.reload()
		self.assertEqual(invoice.supplier, target.name)
		self.assertFalse(self._alias_exists(target.supplier_name))

	def test_supplier_tax_id_learned_when_unique(self):
		suffix = frappe.generate_hash(length=6).upper()
		new_tax_id = f"FR{suffix}LEARN"
		supplier = self._new_supplier(f"Learner {suffix}")

		self._supplier_invoice_stub(supplier.name, new_tax_id)._maybe_update_supplier_tax_id()

		self.assertEqual(frappe.db.get_value("Supplier", supplier.name, "tax_id"), new_tax_id)

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
