# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Pure-logic tests for the CTC transaction classifier. No DB writes — the few
``frappe.db.get_value`` reads are mocked."""

from unittest.mock import patch

from frappe import _dict
from frappe.tests import UnitTestCase

from etransactions.plateforme_agreee.classification import (
	EINVOICED,
	EREPORTED,
	TransactionClass,
	classify_transaction,
	is_einvoicing_required,
	is_vat_registered,
)


def _gv(row, *, country=None, primary_address=None):
	"""Build a frappe.db.get_value side_effect for one party + address."""

	def gv(doctype, name, fieldname=None, as_dict=False, **kw):
		if as_dict and isinstance(fieldname, (list, tuple)):
			return _dict(row)
		if doctype == "Address" and fieldname == "country":
			return country
		if fieldname in ("customer_primary_address", "supplier_primary_address"):
			return primary_address
		return None

	return gv


class TestClassifyTransaction(UnitTestCase):
	def _classify(self, row, **kw):
		with patch("frappe.db.get_value", side_effect=_gv(row, **kw)):
			return classify_transaction("_C", "Customer", "_CUST", "_ADDR")

	def test_public_is_b2g(self):
		self.assertEqual(self._classify({"directory_entity_type": "public"}), TransactionClass.B2G)

	def test_private_is_b2b(self):
		self.assertEqual(self._classify({"directory_entity_type": "private"}), TransactionClass.B2B_DOMESTIC)

	def test_unsynced_business_with_siren_is_b2b(self):
		row = {"directory_entity_type": None, "siren_number": "853322915"}
		self.assertEqual(self._classify(row), TransactionClass.B2B_DOMESTIC)

	def test_private_inactive_is_b2c(self):
		self.assertEqual(
			self._classify({"directory_entity_type": "private_inactive"}), TransactionClass.B2C
		)

	def test_individual_without_siren_is_b2c(self):
		row = {"directory_entity_type": "no", "customer_type": "Individual"}
		self.assertEqual(self._classify(row, country="France"), TransactionClass.B2C)

	def test_foreign_business_is_b2bi(self):
		row = {"directory_entity_type": "no", "customer_type": "Company", "tax_id": "DE123456789"}
		self.assertEqual(self._classify(row, country="Germany"), TransactionClass.B2BI)

	def test_foreign_individual_is_b2c(self):
		row = {"directory_entity_type": "no", "customer_type": "Individual"}
		self.assertEqual(self._classify(row, country="Germany"), TransactionClass.B2C)

	def test_invalid_party_type_is_out_of_scope(self):
		self.assertEqual(
			classify_transaction("_C", "Lead", "_X", None), TransactionClass.OUT_OF_SCOPE
		)

	def test_einvoiced_and_ereported_partition(self):
		# Every non-out-of-scope class is in exactly one leg.
		all_classes = {c for c in TransactionClass if c != TransactionClass.OUT_OF_SCOPE}
		self.assertEqual(set(EINVOICED) | set(EREPORTED), all_classes)
		self.assertEqual(set(EINVOICED) & set(EREPORTED), set())


class TestEinvoicingRequired(UnitTestCase):
	def test_requires_vat_registered_seller(self):
		with patch("frappe.db.get_value", return_value="853322915"):  # company has SIREN
			self.assertTrue(is_vat_registered("_C"))
			self.assertTrue(is_einvoicing_required("_C", TransactionClass.B2B_DOMESTIC))
			self.assertTrue(is_einvoicing_required("_C", TransactionClass.B2G))
			# e-reported classes are never "e-invoicing required"
			self.assertFalse(is_einvoicing_required("_C", TransactionClass.B2C))
			self.assertFalse(is_einvoicing_required("_C", TransactionClass.B2BI))

	def test_non_vat_registered_seller_never_required(self):
		with patch("frappe.db.get_value", return_value=None):  # company has no SIREN
			self.assertFalse(is_vat_registered("_C"))
			self.assertFalse(is_einvoicing_required("_C", TransactionClass.B2B_DOMESTIC))
