# Copyright (c) 2024, Dokos SAS and Contributors
# See license.txt


from typing import TYPE_CHECKING
from etransactions.tests.utils import eTransactionsTestSuite
from frappe.tests.utils import change_settings
import frappe
from frappe.utils import add_days, flt, getdate
from frappe.utils.data import nowdate

from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
from erpnext.buying.doctype.purchase_order.mapper import make_purchase_receipt
from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice

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

		cn_name = frappe.db.get_value("Purchase Invoice", {"supplier_invoice": credit_note_ppi.name})
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
		"eTransactions Settings",
		{"reconcile_with_purchase_receipts": 1, "auto_submit_purchase_invoices": 1},
	)
	@change_settings("Accounts Settings", {"mandatory_accounting_journal": 0})
	def test_credit_note_allocation_skips_draft_invoice(self):
		pi_sub = self._make_submitted_invoice(5000)
		pi_draft = self._make_submitted_invoice(3000, submit=False)

		credit_note = self._make_credit_note(3000, allocations=[(pi_sub.name, 2000), (pi_draft.name, 1000)])

		cn_name = frappe.db.get_value("Purchase Invoice", {"supplier_invoice": credit_note.name})
		cn = frappe.get_doc("Purchase Invoice", cn_name) # type: ignore

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
		doc = frappe.get_doc({
			"doctype": "Supplier Invoice",
			"supplier": self.supplier.name,
			"company": self.company,
			"bill_no": frappe.generate_hash(length=8),
			"bill_date": posting_date,
			"posting_date": posting_date,
		})
		doc.insert()
		return doc

	def test_purchase_invoice_mapped_from_order_keeps_supplier_invoice_posting_date(self):
		"""The order-first route must not repost the invoice on the day it was mapped."""
		from erpnext.buying.doctype.purchase_order.mapper import make_purchase_invoice as make_pi_from_po

		posting_date = add_days(nowdate(), -45)
		supplier_invoice = self._supplier_invoice_with_posting_date(posting_date)

		po = create_purchase_order(
			supplier=self.supplier.name, company=self.company, qty=1.0, rate=100,
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
		supplier_invoice.append("items", {
			"item_code": "_Test Item",
			"qty": 1,
			"rate": 100,
			"amount": 100,
			"expense_account": self.EXPENSE_ACCOUNT,
		})
		supplier_invoice.save()

		pi = supplier_invoice.get_purchase_invoice(purchase_order_is_mandatory=False)

		self.assertEqual(getdate(pi.posting_date), getdate(posting_date))
		self.assertTrue(pi.set_posting_time)

	# --- Item line prefill ---------------------------------------------------

	def _captured_invoice(self, supplier=None, net_amount=100, ocr_request=None):
		doc = frappe.new_doc("Supplier Invoice")
		doc.supplier = supplier or self.supplier.name
		doc.company = self.company
		doc.posting_date = nowdate()
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
		ocr_request.analysis = frappe.as_json({
			"_children": [{"ITEM": "Abonnement Fibre Pro 39,90 EUR", "PRICE": "39.90", "QUANTITY": "1"}]
		})
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

	def test_supplier_item_mapping_learned_from_a_confirmed_line(self):
		invoice = frappe.new_doc("Supplier Invoice")
		invoice.supplier = self.supplier.name
		invoice.company = self.company
		invoice.posting_date = nowdate()
		invoice.append("items", {
			"item_code": "_Test Item",
			"qty": 1,
			"rate": 42,
			"expense_account": self.EXPENSE_ACCOUNT,
			"supplier_description": "Forfait mensuel 42,00 EUR",
		})
		invoice.insert(ignore_mandatory=True)

		alias = frappe.get_all(
			"eTransactions Supplier Item Alias",
			filters={"supplier": self.supplier.name, "supplier_item_code": "forfait mensuel"},
			fields=["item_code", "expense_account"],
		)
		self.assertEqual(len(alias), 1)
		self.assertEqual(alias[0].item_code, "_Test Item")
		self.assertEqual(alias[0].expense_account, self.EXPENSE_ACCOUNT)

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
		return bool(
			frappe.db.exists("eTransactions Supplier Name Alias", {"vendor_name": vendor_name})
		)

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