# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""A draft Sales Invoice must stay saveable when e-invoicing is not enforced."""

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from etransactions.overrides import sales_invoice
from etransactions.tests.utils import eTransactionsTestSuite

CREATE = "etransactions.overrides.sales_invoice._create_update_einvoice"


def _settings(enable_einvoicing, block_submission):
	values = {
		"enable_einvoicing": enable_einvoicing,
		"block_submission_on_blocking_findings": block_submission,
	}
	return patch.object(
		frappe.db, "get_single_value", side_effect=lambda dt, field, *a, **kw: values.get(field)
	)


def _invoice():
	return SimpleNamespace(name="ACC-SINV-TEST", etransaction_profile="EN 16931", docstatus=0)


class TestDraftSaveNeverBlocks(eTransactionsTestSuite):
	def test_einvoicing_off_skips_generation(self):
		with _settings(0, 0), patch(CREATE) as create:
			sales_invoice.on_update(_invoice(), "on_update")
		create.assert_not_called()

	def test_generator_error_does_not_block_a_draft(self):
		with _settings(1, 0), patch(CREATE, side_effect=ValueError("bad xml")), patch.object(
			frappe, "log_error"
		) as log_error, patch.object(frappe, "msgprint") as msgprint:
			sales_invoice.on_update(_invoice(), "on_update")
		log_error.assert_called_once()
		msgprint.assert_called_once()

	def test_generator_error_still_blocks_when_enforced(self):
		with _settings(1, 1), patch(CREATE, side_effect=ValueError("bad xml")):
			with self.assertRaises(ValueError):
				sales_invoice.on_update(_invoice(), "on_update")


class TestPartialPaymentAmountProfile(eTransactionsTestSuite):
	def _terms_xml(self, profile):
		from drafthorse.models.document import Document

		from etransactions.etransactions.doctype.einvoice.generator import EInvoiceGenerator
		from etransactions.utils import EInvoiceProfile

		rows = [
			SimpleNamespace(due="2026-10-19", partial_amount=50, discount_actual_amount=0,
				discount_calculation_percent=0, discount_basis_date=None),
			SimpleNamespace(due="2026-11-19", partial_amount=50, discount_actual_amount=0,
				discount_calculation_percent=0, discount_basis_date=None),
		]
		generator = EInvoiceGenerator.__new__(EInvoiceGenerator)
		generator.profile = EInvoiceProfile(profile)
		generator.einvoice = SimpleNamespace(payment_terms=rows)
		generator.doc = Document()
		generator._add_payment_terms()
		return generator.doc.trade.settlement.terms.children

	def test_partial_amount_only_on_extended(self):
		from etransactions.utils import EInvoiceProfile

		basic = self._terms_xml(EInvoiceProfile.EN16931.value)
		extended = self._terms_xml(EInvoiceProfile.EXTENDED.value)
		self.assertFalse(any(t.partial_amount.children for t in basic))
		self.assertTrue(all(t.partial_amount.children for t in extended))
