# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import patch

from frappe import _dict
from frappe.tests import UnitTestCase

from etransactions.components.superpdp.client import _ereporting_payload
from etransactions.components.superpdp.models import (
	B2CTransaction,
	B2CTransactionSubtotal,
)
from etransactions.plateforme_agreee import ereporting_status as es
from etransactions.plateforme_agreee import session
from etransactions.plateforme_agreee.ereporting import _tax_subtotals, should_ereport_sale


class TestEreportingStatus(UnitTestCase):
	"""Pure-logic tests for the PPF e-reporting status registry. No DB access."""

	def test_state_for_known_and_unknown(self):
		self.assertEqual(es.state_for("ppf:ereporting"), "sent")
		self.assertEqual(es.state_for("ppf:ereporting-response-ok"), "done")
		self.assertEqual(es.state_for("ppf:ereporting-rejected"), "rejected")
		# Unknown codes degrade to the initial "sent" state.
		self.assertEqual(es.state_for("ppf:unknown"), "sent")

	def test_is_warning(self):
		self.assertTrue(es.is_warning("ppf:ereporting-rejected"))
		self.assertTrue(es.is_warning("ppf:ereporting-ack-error"))
		self.assertFalse(es.is_warning("ppf:ereporting-ack"))

	def test_derive_state_picks_most_advanced(self):
		# response-ok outranks the earlier submit/ack events.
		codes = ["ppf:ereporting", "ppf:ereporting-ack", "ppf:ereporting-response-ok"]
		self.assertEqual(es.derive_state(codes), "done")
		# A rejection outranks a plain ack.
		self.assertEqual(es.derive_state(["ppf:ereporting-ack", "ppf:ereporting-rejected"]), "rejected")
		# Empty list -> initial state.
		self.assertEqual(es.derive_state([]), "sent")

	def test_every_status_has_a_label(self):
		for vals in es.STATUSES.values():
			self.assertIn(vals["state"], es.STATE_LABELS)


class TestCapabilityFlag(UnitTestCase):
	def test_only_superpdp_supports_ereporting(self):
		self.assertTrue(session.platform_supports("SuperPDP", "ereporting"))
		self.assertFalse(session.platform_supports("Esalink", "ereporting"))
		self.assertFalse(session.platform_supports("Custom", "ereporting"))
		self.assertFalse(session.platform_supports("Nope", "ereporting"))


class TestPayloadSerialization(UnitTestCase):
	def test_drops_id_and_none(self):
		txn = B2CTransaction(
			date="2026-06-05",
			currency="EUR",
			category_code="TLB1",
			tax_exclusive_amount="100",
			tax_total="20",
			role_code="SE",
			tax_subtotals=[B2CTransactionSubtotal("20", "100", "20")],
			id="should-drop",
			tax_due_date_type_code=None,
		)
		payload = _ereporting_payload(txn)
		self.assertNotIn("id", payload)
		self.assertNotIn("tax_due_date_type_code", payload)  # None dropped
		self.assertEqual(payload["currency"], "EUR")
		self.assertEqual(payload["tax_subtotals"][0]["taxable_amount"], "100")


class TestTaxSubtotals(UnitTestCase):
	"""_tax_subtotals groups percentage VAT rows by rate and recovers the base."""

	def test_recovers_base_from_tax(self):
		doc = _dict(
			net_total=100.0,
			taxes=[_dict(charge_type="On Net Total", rate=20.0, tax_amount=20.0)],
		)
		rows = _tax_subtotals(doc)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["tax_percent"], 20.0)
		self.assertEqual(rows[0]["taxable_amount"], 100.0)
		self.assertEqual(rows[0]["tax_total"], 20.0)

	def test_groups_rows_at_same_rate(self):
		# Two rows at the same rate collapse into one line with summed tax.
		doc = _dict(
			net_total=300.0,
			taxes=[
				_dict(charge_type="On Net Total", rate=20.0, tax_amount=20.0),
				_dict(charge_type="On Net Total", rate=20.0, tax_amount=40.0),
			],
		)
		rows = _tax_subtotals(doc)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["tax_percent"], 20.0)
		self.assertEqual(rows[0]["tax_total"], 60.0)
		self.assertEqual(rows[0]["taxable_amount"], 300.0)

	def test_multiple_rates_sorted(self):
		doc = _dict(
			net_total=200.0,
			taxes=[
				_dict(charge_type="On Net Total", rate=20.0, tax_amount=20.0),
				_dict(charge_type="On Net Total", rate=5.5, tax_amount=5.5),
			],
		)
		rows = _tax_subtotals(doc)
		self.assertEqual([r["tax_percent"] for r in rows], [5.5, 20.0])

	def test_skips_non_percentage_rows(self):
		# An 'Actual' fixed charge carries no VAT rate and is ignored.
		doc = _dict(
			net_total=100.0,
			taxes=[
				_dict(charge_type="On Net Total", rate=20.0, tax_amount=20.0),
				_dict(charge_type="Actual", rate=0.0, tax_amount=7.0),
			],
		)
		rows = _tax_subtotals(doc)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["tax_percent"], 20.0)

	def test_no_taxes_falls_back_to_net_total(self):
		doc = _dict(net_total=80.0, taxes=[])
		rows = _tax_subtotals(doc)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["tax_percent"], 0)
		self.assertEqual(rows[0]["taxable_amount"], 80.0)

	def test_zero_rate_falls_back_to_net_total(self):
		doc = _dict(net_total=50.0, taxes=[_dict(charge_type="On Net Total", rate=0, tax_amount=0)])
		rows = _tax_subtotals(doc)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["tax_percent"], 0)
		self.assertEqual(rows[0]["taxable_amount"], 50.0)


class TestShouldEreportSale(UnitTestCase):
	"""B2C e-reporting scope: who is reported to the PPF vs. e-invoiced (M3)."""

	def _doc(self, **kw):
		base = {"is_return": 0, "company": "_C", "customer": "_CUST"}
		base.update(kw)
		return _dict(base)

	@patch("etransactions.plateforme_agreee.ereporting.ereporting_platform", return_value=object())
	@patch("frappe.db.get_value")
	def test_registered_business_not_ereported(self, gv, _plat):
		gv.return_value = "private"  # reached as a structured B2B e-invoice
		self.assertFalse(should_ereport_sale(self._doc()))

	@patch("etransactions.plateforme_agreee.ereporting.ereporting_platform", return_value=object())
	@patch("frappe.db.get_value")
	def test_unsynced_business_with_siren_is_held(self, gv, _plat):
		# No resolved directory status yet, but a SIREN is present -> hold, don't
		# mis-declare a French business as B2C.
		values = {"directory_entity_type": None, "siren_number": "853322915"}
		gv.side_effect = lambda dt, name, field: values[field]
		self.assertFalse(should_ereport_sale(self._doc()))

	@patch("etransactions.plateforme_agreee.ereporting.ereporting_platform", return_value=object())
	@patch("frappe.db.get_value")
	def test_individual_without_siren_is_ereported(self, gv, _plat):
		values = {"directory_entity_type": None, "siren_number": None}
		gv.side_effect = lambda dt, name, field: values[field]
		self.assertTrue(should_ereport_sale(self._doc()))

	@patch("etransactions.plateforme_agreee.ereporting.ereporting_platform", return_value=object())
	@patch("frappe.db.get_value")
	def test_confirmed_not_in_directory_is_ereported(self, gv, _plat):
		gv.return_value = "no"  # directory consulted, party not registered
		self.assertTrue(should_ereport_sale(self._doc()))

	@patch("etransactions.plateforme_agreee.ereporting.ereporting_platform", return_value=None)
	def test_no_ereporting_platform(self, _plat):
		self.assertFalse(should_ereport_sale(self._doc()))

	@patch("etransactions.plateforme_agreee.ereporting.ereporting_platform", return_value=object())
	def test_return_not_ereported(self, _plat):
		self.assertFalse(should_ereport_sale(self._doc(is_return=1)))
