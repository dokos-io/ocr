# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

"""Gap A regression: for every VAT category other than S/Z, the *document-level*
VAT breakdown must carry a VAT exemption reason — code (BT-121) and text (BT-120).

Required by EN16931 (BR-E/AE/G/IC/O-10) and mandatory at document level from the
FNFE Schematrons FR CTC v1.4.0 EXTENDED / CTC-FR profiles (XP Z12-012 V1.4.0).
The category and reason lookups are code-list driven, so they are patched here to
force an exempt category deterministically, independent of the site's seed data.
"""

from unittest.mock import patch

from frappe.tests import UnitTestCase

from etransactions.etransactions.doctype.einvoice import generator as cii_mod
from etransactions.etransactions.doctype.einvoice import ubl_generator as ubl_mod
from etransactions.etransactions.doctype.einvoice.generator import EInvoiceGenerator
from etransactions.etransactions.doctype.einvoice.ubl_generator import UBLGenerator
from etransactions.tests.test_ubl_generator import (
	_fixture_company,
	_fixture_customer,
	_fixture_einvoice,
)
from etransactions.utils import EInvoiceProfile, get_drafthorse_schema

_EXEMPT_CODE = "vatex-eu-132"
_EXEMPT_TEXT = "Exonération TVA - article 132 directive 2006/112/CE"

_EXEMPT_OVERRIDES = dict(
	tax_total=0.0,
	grand_total=100.0,
	due_payable=100.0,
	items=[
		{
			"product_name": "Consulting",
			"seller_product_id": "CONS-1",
			"product_description": "Consulting services",
			"billed_quantity": 1.0,
			"unit_code": "C62",
			"net_rate": 100.0,
			"tax_rate": 0.0,
			"total_amount": 100.0,
		}
	],
	taxes=[{"basis_amount": 100.0, "rate_applicable_percent": 0.0, "calculated_amount": 0.0}],
	payment_terms=[{"due": "2026-07-31", "partial_amount": 100.0}],
)


def _force_exempt(module):
	"""Patch a generator module's code-list singletons to a fixed exempt category."""
	return (
		patch.object(module.duty_tax_fee_category_codes, "get", return_value="E"),
		patch.object(module.vat_exemption_reason_codes, "get", return_value=_EXEMPT_CODE),
		patch.object(
			module.vat_exemption_reason_codes, "get_description", return_value=_EXEMPT_TEXT
		),
	)


def _generate_cii(einvoice, profile=EInvoiceProfile.EXTENDED) -> str:
	gen = EInvoiceGenerator(
		profile=profile,
		einvoice=einvoice,
		company=_fixture_company(),
		customer=_fixture_customer(),
	)
	gen.create_einvoice()
	doc = gen.get_einvoice()
	return doc.serialize(schema=get_drafthorse_schema(profile)).decode()


def _generate_ubl(einvoice) -> str:
	gen = UBLGenerator(
		profile=EInvoiceProfile.EN16931,
		einvoice=einvoice,
		company=_fixture_company(),
		customer=_fixture_customer(),
	)
	gen.create_einvoice()
	return gen.serialize().decode()


class TestDocumentLevelExemptionReason(UnitTestCase):
	def test_cii_exempt_emits_reason_code_and_text(self):
		p1, p2, p3 = _force_exempt(cii_mod)
		with p1, p2, p3:
			xml = _generate_cii(_fixture_einvoice(**_EXEMPT_OVERRIDES))
		self.assertIn("ExemptionReasonCode", xml)
		self.assertIn(_EXEMPT_CODE.upper(), xml)
		self.assertIn("ExemptionReason", xml)
		self.assertIn(_EXEMPT_TEXT, xml)

	def test_cii_standard_emits_no_reason(self):
		# The stock S/20% fixture must not carry any exemption reason.
		xml = _generate_cii(_fixture_einvoice())
		self.assertNotIn("ExemptionReason", xml)

	def test_ubl_exempt_emits_reason_code_and_text(self):
		p1, p2, p3 = _force_exempt(ubl_mod)
		with p1, p2, p3:
			xml = _generate_ubl(_fixture_einvoice(**_EXEMPT_OVERRIDES))
		self.assertIn("TaxExemptionReasonCode", xml)
		self.assertIn(_EXEMPT_CODE.upper(), xml)
		self.assertIn("TaxExemptionReason>", xml)
		self.assertIn(_EXEMPT_TEXT, xml)

	def test_ubl_standard_emits_no_reason(self):
		xml = _generate_ubl(_fixture_einvoice())
		self.assertNotIn("TaxExemptionReason", xml)
