# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from etransactions.etransactions.doctype.einvoice.generator import resolve_syntax
from etransactions.etransactions.doctype.einvoice.ubl_generator import UBLGenerator
from etransactions.schematron import get_validation_errors
from etransactions.utils import EInvoiceProfile
from etransactions.utils.ubl_parser import parse_ubl


def _fixture_einvoice(**overrides):
	data = {
		"doctype": "eInvoice",
		"einvoice_type": "Outgoing",
		"id": "SINV-UBL-0001",
		"issue_date": "2026-07-01",
		"due_date": "2026-07-31",
		"currency": "EUR",
		"company": "_Test Company",
		"is_return": 0,
		"buyer_reference": "SERVICE-42",
		"purchase_order": "PO-123",
		"seller_name": "Dokos SAS",
		"seller_address_line_1": "12 rue de la Paix",
		"seller_city": "Paris",
		"seller_postcode": "75002",
		"seller_country": "France",
		"seller_tax_id": "FR47533372222",
		"seller_electronic_address": "533372222",
		"seller_electronic_address_scheme": "0009",
		"buyer_name": "Tricatel",
		"buyer_address_line_1": "1 avenue des Champs",
		"buyer_city": "Lyon",
		"buyer_postcode": "69001",
		"buyer_country": "France",
		"buyer_tax_id": "FR23315143296",
		"buyer_electronic_address": "315143296",
		"buyer_electronic_address_scheme": "0009",
		"line_total": 100.0,
		"charge_total": 0.0,
		"tax_basis_total": 100.0,
		"tax_total": 20.0,
		"grand_total": 120.0,
		"total_prepaid": 0.0,
		"due_payable": 120.0,
		"payee_iban": "FR7630006000011234567890189",
		"payee_bic": "AGRIFRPP",
		"payee_account_name": "Dokos SAS",
		"items": [
			{
				"product_name": "Consulting",
				"seller_product_id": "CONS-1",
				"product_description": "Consulting services",
				"billed_quantity": 1.0,
				"unit_code": "C62",
				"net_rate": 100.0,
				"tax_rate": 20.0,
				"total_amount": 100.0,
			}
		],
		"taxes": [
			{
				"basis_amount": 100.0,
				"rate_applicable_percent": 20.0,
				"calculated_amount": 20.0,
			}
		],
		"payment_terms": [{"due": "2026-07-31", "partial_amount": 120.0}],
	}
	data.update(overrides)
	return frappe.get_doc(data)


def _fixture_company():
	return frappe._dict({"siren_number": "533372222", "phone_no": None})


def _fixture_customer():
	return frappe._dict({"siren_number": "315143296", "supplier_numbers": []})


def _generate(einvoice) -> str:
	gen = UBLGenerator(
		profile=EInvoiceProfile.EN16931,
		einvoice=einvoice,
		company=_fixture_company(),
		customer=_fixture_customer(),
	)
	gen.create_einvoice()
	return gen.serialize().decode()


class TestUBLGeneration(UnitTestCase):
	"""The UBL builder must produce Peppol BIS 3.0 documents that pass both the
	EN16931-UBL and Peppol schematrons and round-trip through our own parser."""

	def test_invoice_passes_en16931_and_peppol_schematron(self):
		xml = _generate(_fixture_einvoice())
		errors, warnings = get_validation_errors(xml, EInvoiceProfile.EN16931, "UBL")
		self.assertEqual(errors, [], "\n".join(errors))
		self.assertEqual(warnings, [], "\n".join(warnings))

	def test_invoice_structure(self):
		xml = _generate(_fixture_einvoice())
		self.assertIn("<Invoice", xml)
		self.assertIn("urn:fdc:peppol.eu:2017:poacc:billing:3.0", xml)
		self.assertIn("<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>", xml)
		# French domestic → the three mandatory mentions in the single note
		for subject_code in ("#PMD#", "#PMT#", "#AAB#"):
			self.assertIn(subject_code, xml)

	def test_billing_framework_note(self):
		# BT-21/BT-22 must be explicit: BAR = B2B for businesses, ADN = B2G for
		# the public sector, flattened into the single Peppol note.
		self.assertIn("#BAR#B2B", _generate(_fixture_einvoice(pa_processing_rule="B2B")))
		self.assertIn("#ADN#B2G", _generate(_fixture_einvoice(pa_processing_rule="B2G")))

	def test_credit_note_root_and_billing_reference(self):
		xml = _generate(_fixture_einvoice(is_return=1, return_against="SINV-0042", due_date=None))
		self.assertIn("<CreditNote", xml)
		self.assertIn("<cbc:CreditNoteTypeCode>381</cbc:CreditNoteTypeCode>", xml)
		self.assertIn("<cbc:ID>SINV-0042</cbc:ID>", xml)  # BillingReference
		self.assertIn("<cac:CreditNoteLine>", xml)
		errors, _warnings = get_validation_errors(xml, EInvoiceProfile.EN16931, "UBL")
		self.assertEqual(errors, [], "\n".join(errors))

	def test_round_trip_through_own_parser(self):
		source = _fixture_einvoice()
		xml = _generate(source)

		parsed = frappe.get_doc({"doctype": "eInvoice", "einvoice_type": "Incoming"})
		parse_ubl(xml.encode(), parsed)

		self.assertEqual(parsed.id, source.id)
		self.assertEqual(str(parsed.issue_date), str(source.issue_date))
		self.assertEqual(str(parsed.due_date), str(source.due_date))
		self.assertEqual(parsed.currency, source.currency)
		self.assertEqual(parsed.profile, "EN16931")
		self.assertEqual(parsed.seller_name, source.seller_name)
		self.assertEqual(parsed.seller_tax_id, source.seller_tax_id)
		self.assertEqual(parsed.seller_electronic_address, source.seller_electronic_address)
		self.assertEqual(parsed.buyer_name, source.buyer_name)
		self.assertEqual(parsed.buyer_tax_id, source.buyer_tax_id)
		self.assertEqual(len(parsed.items), 1)
		self.assertEqual(parsed.items[0].product_name, "Consulting")
		self.assertEqual(parsed.items[0].billed_quantity, 1.0)
		self.assertEqual(parsed.items[0].net_rate, 100.0)
		self.assertEqual(parsed.items[0].total_amount, 100.0)
		self.assertEqual(len(parsed.taxes), 1)
		self.assertEqual(parsed.taxes[0].basis_amount, 100.0)
		self.assertEqual(parsed.taxes[0].calculated_amount, 20.0)
		self.assertEqual(parsed.grand_total, 120.0)
		self.assertEqual(parsed.due_payable, 120.0)
		self.assertEqual(parsed.payee_iban, source.payee_iban)
		self.assertEqual(parsed.payee_bic, source.payee_bic)

	def test_get_file_for_pa_ubl_branch(self):
		einvoice = _fixture_einvoice(sales_invoice=None)
		einvoice.syntax = "UBL"
		einvoice.sales_invoice = "SINV-UBL-0001"
		einvoice.einvoice_xml = "<Invoice/>"
		content, filename, syntax = einvoice._get_file_for_pa()
		self.assertEqual(content, b"<Invoice/>")
		self.assertEqual(filename, "SINV-UBL-0001.xml")
		self.assertEqual(syntax, "UBL")


class TestResolveSyntax(UnitTestCase):
	"""Syntax resolution: profile override → Peppol signals → CII default; only
	EN16931/XRechnung profiles may go UBL."""

	def _resolve(
		self,
		profile="EN16931",
		default_syntax=None,
		directory_type=None,
		identifier=None,
		routing_line="LINE-1",
		peppol_enabled=True,
	):
		sales_invoice = frappe._dict(
			{"etransaction_profile": profile, "customer": "CUST-1", "customer_address": None}
		)
		einvoice = frappe._dict()

		def db_get_value(doctype, name, fieldname=None, *args, **kwargs):
			if doctype == "eTransaction Profile":
				return default_syntax
			if doctype == "Customer":
				return directory_type
			if doctype == "eInvoicing Directory Line":
				return identifier
			return None

		with (
			patch(
				"etransactions.etransactions.doctype.einvoice.generator.frappe.db.get_value",
				side_effect=db_get_value,
			),
			patch(
				"etransactions.plateforme_agreee.routing.resolve_routing",
				return_value=routing_line,
			),
			patch(
				"etransactions.etransactions.doctype.einvoice.generator.is_feature_enabled",
				side_effect=lambda feature: peppol_enabled and feature == "peppol",
			),
		):
			return resolve_syntax(einvoice, sales_invoice)

	def test_factur_x_only_without_peppol_feature(self):
		"""Without the Peppol network feature, no signal can switch an invoice to UBL."""
		self.assertEqual(self._resolve(directory_type="peppol", peppol_enabled=False), "CII")
		self.assertEqual(self._resolve(default_syntax="UBL", peppol_enabled=False), "CII")
		self.assertEqual(self._resolve(identifier="0088:1234567890123", peppol_enabled=False), "CII")

	def test_non_en16931_profiles_stay_cii(self):
		for profile in ("MINIMUM", "BASIC WL", "BASIC", "EXTENDED", "EXTENDED CTC-FR"):
			self.assertEqual(self._resolve(profile=profile, directory_type="peppol"), "CII")

	def test_profile_default_syntax_wins(self):
		self.assertEqual(self._resolve(default_syntax="UBL"), "UBL")
		self.assertEqual(self._resolve(default_syntax="CII", directory_type="peppol"), "CII")

	def test_peppol_directory_type_selects_ubl(self):
		self.assertEqual(self._resolve(directory_type="peppol"), "UBL")

	def test_non_french_identifier_scheme_selects_ubl(self):
		self.assertEqual(self._resolve(identifier="0088:1234567890123"), "UBL")
		self.assertEqual(self._resolve(identifier="0225:315143296"), "CII")

	def test_default_is_cii(self):
		self.assertEqual(self._resolve(routing_line=None), "CII")
		self.assertEqual(self._resolve(profile="FACTUR-X", routing_line=None), "CII")
