# Copyright (c) 2026, Dokos SAS and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
from frappe.tests.utils import change_settings
from frappe.utils import nowdate

from etransactions.etransactions.doctype.supplier_invoice.processing_guide import ProcessingGuide
from etransactions.etransactions.doctype.supplier_invoice.test_supplier_invoice import (
	create_item,
	create_supplier,
)
from etransactions.tests.utils import eTransactionsTestSuite

EXPENSE_ACCOUNT = "_Test Account Cost for Goods Sold - _TC"
COMPANY = "_Test Company"


class TestProcessingGuide(eTransactionsTestSuite):
	def setUp(self):
		for doctype in ("Purchase Invoice", "Supplier Invoice", "Purchase Order"):
			frappe.db.delete(doctype)
		self.supplier = create_supplier()
		create_item()

	def tearDown(self):
		frappe.db.rollback()

	def make_invoice(self, items=1, net_amount=100, **kwargs):
		doc = frappe.new_doc("Supplier Invoice")
		doc.update(
			{
				"supplier": self.supplier.name,
				"company": COMPANY,
				"posting_date": nowdate(),
				"bill_no": frappe.generate_hash(length=8),
				"supplier_net_amount": net_amount,
				**kwargs,
			}
		)
		for _i in range(items):
			doc.append(
				"items",
				{
					"item_code": "_Test Item",
					"qty": 1,
					"rate": net_amount / items,
					"amount": net_amount / items,
					"expense_account": EXPENSE_ACCOUNT,
				},
			)
		doc.insert(ignore_mandatory=True)
		return doc

	def guide(self, doc):
		return ProcessingGuide(frappe.get_doc("Supplier Invoice", doc.name)).as_dict()

	def check(self, guide, key):
		return next((c for c in guide["checks"] if c["key"] == key), None)

	# --- Review -----------------------------------------------------------------------

	def test_unknown_supplier_is_to_review(self):
		doc = self.make_invoice(supplier=None, tax_id="FR32552100554")

		guide = self.guide(doc)

		self.assertEqual(guide["status"]["key"], "to_review")
		self.assertEqual(self.check(guide, "supplier")["state"], "error")
		self.assertEqual(guide["next_step"]["primary"]["action"], "create_supplier")
		self.assertEqual(guide["steps"][1]["state"], "current")

	def test_line_without_item_is_to_review(self):
		doc = self.make_invoice(items=2)
		doc.items[1].item_code = None
		doc.save()

		guide = self.guide(doc)

		self.assertEqual(guide["status"]["key"], "to_review")
		missing = self.check(guide, "items_missing")
		self.assertEqual(missing["rows"], [2])
		self.assertEqual(guide["next_step"]["primary"], {"action": "pick_item", "label": "Choose", "row": 2})

	@change_settings("eTransactions Settings", {"no_purchase_order": 1})
	def test_suggested_item_is_a_warning_not_a_blocker(self):
		doc = self.make_invoice()
		doc.items[0].item_match = "Suggested"
		doc.save()

		guide = self.guide(doc)

		self.assertEqual(guide["status"]["key"], "ready")
		self.assertEqual(self.check(guide, "items_suggested")["state"], "warning")

	def test_item_changed_by_the_user_is_manual(self):
		doc = self.make_invoice()
		doc.items[0].item_match = "Suggested"
		doc.save()

		other = frappe.get_doc(
			{"doctype": "Item", "item_code": "_Test Item Guide", "item_group": "All Item Groups"}
		)
		other.insert(ignore_if_duplicate=True)
		doc.items[0].item_code = "_Test Item Guide"
		doc.save()

		self.assertEqual(doc.items[0].item_match, "Manual")

	def test_invoice_already_booked_elsewhere_is_to_review(self):
		first = self.make_invoice()
		pi = first.get_purchase_invoice(purchase_order_is_mandatory=False)
		pi.insert(ignore_mandatory=True)
		pi.submit()

		duplicate = self.make_invoice(bill_no=first.bill_no)

		guide = self.guide(duplicate)
		self.assertEqual(guide["status"]["key"], "to_review")
		self.assertEqual(self.check(guide, "duplicate")["action"]["name"], pi.name)

	# --- Match the order ----------------------------------------------------------------

	def test_order_required_and_not_linked_is_to_match(self):
		doc = self.make_invoice()

		guide = self.guide(doc)

		self.assertEqual(guide["status"]["key"], "to_match")
		self.assertEqual(self.check(guide, "order_link")["state"], "todo")
		self.assertEqual(guide["steps"][2]["state"], "current")

	@change_settings("eTransactions Settings", {"no_purchase_order": 1})
	def test_no_order_required_is_ready_and_skips_the_step(self):
		doc = self.make_invoice()

		guide = self.guide(doc)

		self.assertEqual(guide["status"]["key"], "ready")
		self.assertIsNone(self.check(guide, "order_link"))
		self.assertEqual(guide["steps"][2]["state"], "skipped")
		self.assertEqual(guide["next_step"]["primary"]["action"], "create_purchase_invoice")

	def test_link_order_links_the_existing_lines(self):
		po = create_purchase_order(
			supplier=self.supplier.name, company=COMPANY, qty=1, rate=100, warehouse="_Test Warehouse - _TC"
		)
		doc = self.make_invoice()

		result = doc.link_purchase_document("Purchase Order", po.name)

		doc.reload()
		self.assertEqual(result, {"linked": 1, "unlinked": []})
		self.assertEqual(len(doc.items), 1)
		self.assertEqual(doc.items[0].reference_docname, po.name)
		self.assertEqual(doc.items[0].row, po.items[0].name)
		self.assertEqual(self.guide(doc)["status"]["key"], "ready")

	def test_draft_order_keeps_the_invoice_to_match(self):
		po = create_purchase_order(
			supplier=self.supplier.name,
			company=COMPANY,
			qty=1,
			rate=100,
			warehouse="_Test Warehouse - _TC",
			do_not_submit=True,
		)
		doc = self.make_invoice()
		doc.link_purchase_document("Purchase Order", po.name)

		guide = self.guide(doc)

		self.assertEqual(guide["status"]["key"], "to_match")
		self.assertEqual(self.check(guide, "order_draft")["action"]["name"], po.name)

	def test_status_not_ready_while_its_purchase_order_is_a_draft(self):
		"""The draft orders were filtered out before the check, so "Ready" was always set."""
		doc = self.make_invoice()
		po = create_purchase_order(
			supplier=self.supplier.name,
			company=COMPANY,
			qty=1,
			rate=100,
			warehouse="_Test Warehouse - _TC",
			do_not_submit=True,
		)
		frappe.db.set_value("Purchase Order", po.name, "supplier_invoice", doc.name)

		doc.set_status()

		self.assertEqual(doc.status, "In Progress")

	# --- Book and pay -------------------------------------------------------------------

	@change_settings("eTransactions Settings", {"no_purchase_order": 1})
	def test_submitted_purchase_invoice_is_booked_and_stored(self):
		doc = self.make_invoice()

		pi = doc.create_purchase_invoice(submit=True)

		self.assertEqual(frappe.db.get_value("Supplier Invoice", doc.name, "guide_status"), "To Pay")
		guide = self.guide(doc)
		self.assertEqual(guide["status"]["key"], "booked")
		self.assertEqual(
			guide["next_step"]["primary"],
			{"action": "record_payment", "label": "Record payment", "name": pi.name},
		)
		self.assertEqual([s["state"] for s in guide["steps"]][3:], ["done", "current"])

	@change_settings("eTransactions Settings", {"no_purchase_order": 1})
	def test_draft_purchase_invoice_is_opened_rather_than_created_again(self):
		doc = self.make_invoice()
		pi = doc.create_purchase_invoice(submit=False)

		guide = self.guide(doc)

		self.assertEqual(guide["status"]["key"], "ready")
		self.assertEqual(guide["next_step"]["primary"]["action"], "open_doc")
		self.assertEqual(guide["next_step"]["primary"]["name"], pi.name)

	# --- Closed and outside a platform --------------------------------------------------

	def test_closed_invoice_offers_to_reopen(self):
		doc = self.make_invoice()
		doc.close_request()

		guide = self.guide(doc)

		self.assertEqual(guide["status"]["key"], "closed")
		self.assertEqual(guide["next_step"]["primary"]["action"], "reopen")
		self.assertEqual(guide["options"], [])
		self.assertEqual(frappe.db.get_value("Supplier Invoice", doc.name, "guide_status"), "Closed")

	def test_invoice_outside_a_platform_cannot_be_disputed(self):
		doc = self.make_invoice()

		guide = self.guide(doc)

		self.assertEqual(guide["source"], "manual")
		self.assertIsNone(guide["platform"])
		options = {o["key"]: o for o in guide["options"]}
		self.assertTrue(options["platform_unavailable"]["disabled"])
		self.assertEqual(options["close"]["action"]["action"], "close")

	# --- Received through a platform ----------------------------------------------------

	def platform_guide(self, doc, lifecycle, content_state="fetched"):
		einvoice = frappe._dict(
			name="EINV-TEST", einvoice_type="Incoming", pa_flow_id="flow-1", pa_content_state=content_state
		)
		with (
			patch.object(ProcessingGuide, "_get_einvoice", return_value=einvoice),
			patch.object(ProcessingGuide, "_get_lifecycle_state", return_value=lifecycle),
			patch.object(ProcessingGuide, "_get_overview", return_value=None),
		):
			guide = ProcessingGuide(frappe.get_doc("Supplier Invoice", doc.name))
			return guide.status_key(), guide

	def test_disputed_on_the_platform(self):
		doc = self.make_invoice()

		status, guide = self.platform_guide(doc, {"purchase": "dispute"})

		self.assertEqual(status, "disputed")
		self.assertEqual(guide.steps(status)[3]["state"], "skipped")

	def test_refused_on_the_platform(self):
		doc = self.make_invoice()

		status, guide = self.platform_guide(doc, {"purchase": "refused", "refused": True})

		self.assertEqual(status, "refused")
		self.assertEqual(guide.next_step(status, None)["primary"]["action"], "close")

	def test_file_not_downloaded(self):
		doc = self.make_invoice()

		status, _guide = self.platform_guide(doc, {}, content_state="pending")

		self.assertEqual(status, "file_missing")
