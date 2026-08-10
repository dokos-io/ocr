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
from etransactions.etransactions.doctype.einvoice.generator import (
	EInvoiceGenerator,
	resolve_ctc_framework_note,
)

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


class TestCtcFrameworkNote(UnitTestCase):
	"""BT-21/BT-22 billing-framework note: BAR = B2B, ADN = B2G.

	Accredited platforms require the label explicitly, and the FNFE BR-FR-Flux2
	rules only fire once it is present — an unlabelled invoice is treated as B2B
	by default *and* validated less strictly.
	"""

	def _einvoice(self, **fields):
		return SimpleNamespace(seller_country="France", **fields)

	def test_every_transaction_class_is_labelled(self):
		expected = {
			"B2B": ("BAR", "B2B"),
			"B2G": ("ADN", "B2G"),
			"B2Bi": ("BAR", "B2BINT"),
			"B2C": ("BAR", "B2C"),
			"OutOfScope": ("BAR", "OUTOFSCOPE"),
		}
		for rule, note in expected.items():
			with self.subTest(rule=rule):
				self.assertEqual(resolve_ctc_framework_note(self._einvoice(pa_processing_rule=rule)), note)

	def test_b2g_never_uses_the_bar_subject_code(self):
		# BR-FR-20 does not accept B2G as a BAR value — it has its own code, ADN.
		subject_code, _content = resolve_ctc_framework_note(self._einvoice(pa_processing_rule="B2G"))
		self.assertEqual(subject_code, "ADN")

	def test_unset_rule_falls_back_to_b2b(self):
		# Same fallback as the platform submission and as the field default: the
		# point of the note is that the implicit B2B default becomes explicit.
		self.assertEqual(resolve_ctc_framework_note(self._einvoice(pa_processing_rule=None)), ("BAR", "B2B"))

	def test_unknown_rule_emits_nothing(self):
		self.assertIsNone(resolve_ctc_framework_note(self._einvoice(pa_processing_rule="Bogus")))

	def test_foreign_seller_is_out_of_scope(self):
		einvoice = SimpleNamespace(seller_country="Germany", pa_processing_rule="B2B")
		self.assertIsNone(resolve_ctc_framework_note(einvoice))

	def test_french_seller_with_foreign_buyer_is_still_labelled(self):
		# B2BINT has a foreign buyer by definition: gating on French *domestic*
		# would leave the whole international leg unlabelled.
		self.assertEqual(
			resolve_ctc_framework_note(self._einvoice(pa_processing_rule="B2Bi")), ("BAR", "B2BINT")
		)


class TestCtcFrameworkNoteInXml(UnitTestCase):
	"""The note reaches the serialized CII and UBL documents."""

	def _cii_xml(self, processing_rule: str) -> str:
		from etransactions.tests.test_ubl_generator import (
			_fixture_company,
			_fixture_customer,
			_fixture_einvoice,
		)

		einvoice = _fixture_einvoice(pa_processing_rule=processing_rule)
		generator = EInvoiceGenerator(
			profile=EInvoiceProfile.EN16931,
			einvoice=einvoice,
			company=_fixture_company(),
			customer=_fixture_customer(),
		)
		generator.create_einvoice()
		xml = generator.get_einvoice().serialize(schema=get_drafthorse_schema(EInvoiceProfile.EN16931))
		return xml.decode() if isinstance(xml, bytes) else xml

	def test_cii_b2b_note(self):
		xml = self._cii_xml("B2B")
		self.assertIn("<ram:SubjectCode>BAR</ram:SubjectCode>", xml)
		self.assertIn("<ram:Content>B2B</ram:Content>", xml)

	def test_cii_b2g_note(self):
		xml = self._cii_xml("B2G")
		self.assertIn("<ram:SubjectCode>ADN</ram:SubjectCode>", xml)
		self.assertIn("<ram:Content>B2G</ram:Content>", xml)
		# BR-FR-31: never two competing BAR values.
		self.assertNotIn("<ram:SubjectCode>BAR</ram:SubjectCode>", xml)


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
