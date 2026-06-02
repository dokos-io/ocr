# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from etransactions.plateforme_agreee import cdar

# Only the lookups our CDAR builder makes are mocked; everything else (e.g.
# framework-internal get_value calls) is delegated to the real implementation.
_MOCKED = {
	("Company", "siren_number"): "732829320",
	("Company", "company_name"): "Acme SAS",
	("Sales Invoice", "customer"): "Client SARL",
	("Sales Invoice", "is_return"): 0,
	("Customer", "siren_number"): "552100554",
	("eInvoicing Directory Line", None): "552100554",
}


def _router(orig):
	def _fake(doctype=None, filters=None, fieldname=None, *args, **kwargs):
		dt = doctype if doctype is not None else kwargs.get("doctype")
		fn = fieldname if fieldname is not None else kwargs.get("fieldname")
		if (dt, fn) in _MOCKED:
			return _MOCKED[(dt, fn)]
		if dt == "eInvoicing Directory Line":
			return _MOCKED[("eInvoicing Directory Line", None)]
		return orig(doctype, filters, fieldname, *args, **kwargs)

	return _fake


def _outgoing():
	return SimpleNamespace(
		company="ACME", einvoice_type="Outgoing", id="INV-0001", issue_date="2026-05-20",
		sales_invoice="ACC-SINV-0001", buyer_name="Client SARL",
		buyer_electronic_address="0009:73282932000074",
	)


def _incoming():
	return SimpleNamespace(
		company="ACME", einvoice_type="Incoming", id="SUP-77", issue_date="2026-05-18",
		sales_invoice=None, seller_name="Fournisseur SA",
		seller_electronic_address="73282932000074", seller_electronic_address_scheme="0009",
		seller_tax_id="FR12732829320",
	)


class TestCdarBuilder(UnitTestCase):
	"""Validate that build_cdar_data() output passes pyfrctc's XSD + Schematron.

	generate_cdar_flow() raises if validation fails, so a returned byte string
	means the CDAR is structurally and semantically valid against the official
	CTC schematron. SIREN/name lookups are mocked; no DB writes occur.
	"""

	# (einvoice factory, canonical status, details)
	CASES = [
		(_outgoing, "completed", None),
		(_outgoing, "payment_received", [{"amount": 120.0, "currency": "EUR", "payment_date": "2026-05-25"}]),
		(_incoming, "in_hand", None),
		(_incoming, "approved", None),
		(_incoming, "partially_approved", [{"reason_code": "QTE_ERR"}]),
		(_incoming, "dispute", [{"reason_code": "NON_CONFORME", "comment": "litige"}]),
		(_incoming, "suspended", [{"reason_code": "JUSTIF_ABS"}]),
		(_incoming, "refused", [{"reason_code": "NON_CONFORME"}]),
		(_incoming, "payment_sent", [{"amount": 90.0, "currency": "EUR", "payment_date": "2026-05-26"}]),
	]

	def test_all_statuses_pass_schematron(self):
		with patch("frappe.db.get_value", side_effect=_router(frappe.db.get_value)):
			for factory, status, details in self.CASES:
				with self.subTest(status=status):
					cdar_bytes, filename = cdar.generate_cdar_flow(factory(), status, details=details)
					self.assertTrue(cdar_bytes and len(cdar_bytes) > 0)
					self.assertTrue(filename.endswith(".xml"))
