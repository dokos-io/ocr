# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from etransactions.utils import (
	EInvoiceProfile,
	get_drafthorse_schema,
	get_guideline,
)
from etransactions.utils.facturx_pdf import _PROFILE_TO_FACTURX_LEVEL
from etransactions.schematron import PROFILE_TO_XSL
from etransactions.overrides.sales_invoice import _apply_b2g

CTC_FR_GUIDELINE = "urn.cpro.gouv.fr:1p0:extended-ctc-fr"


class TestCtcFrProfile(UnitTestCase):
	"""Pure-logic wiring of the French CTC-FR profile (no DB)."""

	def test_profile_registered(self):
		self.assertEqual(EInvoiceProfile.CTC_FR.value, "EXTENDED CTC-FR")
		self.assertEqual(get_guideline(EInvoiceProfile.CTC_FR), CTC_FR_GUIDELINE)
		# CTC-FR is Extended-based: reuse the drafthorse extended schema + facturx level.
		self.assertEqual(get_drafthorse_schema(EInvoiceProfile.CTC_FR), "FACTUR-X_EXTENDED")
		self.assertEqual(_PROFILE_TO_FACTURX_LEVEL[EInvoiceProfile.CTC_FR], "extended")
		self.assertIn(EInvoiceProfile.CTC_FR, PROFILE_TO_XSL)

	def test_profile_ordering(self):
		# CTC-FR must rank at/above EXTENDED so `profile >= EXTENDED` gates still pass.
		self.assertTrue(EInvoiceProfile.CTC_FR >= EInvoiceProfile.EXTENDED)

	def test_b2g_upgrades_profile(self):
		doc = SimpleNamespace(etransaction_profile="EN16931", etransactions_buyer_reference="SVC1")
		with patch("frappe.msgprint"):
			_apply_b2g(doc)
		self.assertEqual(doc.etransaction_profile, "EXTENDED CTC-FR")

	def test_b2g_does_not_downgrade_or_touch_foreign_profile(self):
		doc = SimpleNamespace(etransaction_profile="FACTUR-X", etransactions_buyer_reference="SVC1")
		with patch("frappe.msgprint"):
			_apply_b2g(doc)
		# XRechnung (German B2G) profile must not be overwritten.
		self.assertEqual(doc.etransaction_profile, "FACTUR-X")


class TestCtcFrGeneration(IntegrationTestCase):
	"""End-to-end: a CTC-FR Sales Invoice emits the French guideline and BT-12 contract."""

	def test_ctc_fr_xml_has_guideline_and_contract(self):
		company = "_Test Company"
		if not frappe.db.exists("Customer", "_Test Customer"):
			frappe.get_doc({
				"doctype": "Customer",
				"customer_name": "_Test Customer",
				"customer_group": "All Customer Groups",
				"territory": "All Territories",
			}).insert()

		if not frappe.db.exists("Item", "_Test Item 1"):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": "_Test Item 1",
				"item_group": "All Item Groups",
				"is_stock_item": 0,
			}).insert()

		si = frappe.new_doc("Sales Invoice")
		si.company = company
		si.customer = "_Test Customer"
		si.currency = "INR"
		si.posting_date = frappe.utils.today()
		si.etransaction_profile = "EXTENDED CTC-FR"
		si.etransactions_buyer_reference = "SERVICE-EXEC-01"
		si.etransactions_contract_reference = "MARCHE-2026-042"
		si.append("items", {"item_code": "_Test Item 1", "qty": 1, "rate": 100.0})
		si.insert()

		einvoice_name = frappe.db.exists("eInvoice", {"sales_invoice": si.name})
		self.assertTrue(einvoice_name)
		einvoice = frappe.get_doc("eInvoice", einvoice_name)

		self.assertEqual(einvoice.profile, "EXTENDED CTC-FR")
		self.assertEqual(einvoice.contract_reference, "MARCHE-2026-042")

		xml = einvoice.einvoice_xml
		xml_str = xml.decode() if isinstance(xml, bytes) else (xml or "")
		# BT-24 guideline carries the French CTC-FR profile id.
		self.assertIn(CTC_FR_GUIDELINE, xml_str)
		# BT-12 ContractReferencedDocument carries the numéro de marché.
		self.assertIn("MARCHE-2026-042", xml_str)
