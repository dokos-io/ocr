# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

from frappe import _dict
from frappe.tests import UnitTestCase

from etransactions.components.superpdp.client import _ereporting_payload
from etransactions.components.superpdp.models import (
	B2CTransaction,
	B2CTransactionSubtotal,
)
from etransactions.plateforme_agreee import ereporting_status as es
from etransactions.plateforme_agreee import session
from etransactions.plateforme_agreee.ereporting import _tax_subtotals


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
	"""_tax_subtotals recovers the taxable base from each percentage tax row."""

	def test_recovers_base_from_tax(self):
		doc = _dict(
			net_total=100.0,
			taxes=[_dict(rate=20.0, tax_amount=20.0)],
		)
		rows = _tax_subtotals(doc)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["tax_percent"], 20.0)
		self.assertEqual(rows[0]["taxable_amount"], 100.0)
		self.assertEqual(rows[0]["tax_total"], 20.0)

	def test_no_taxes_falls_back_to_net_total(self):
		doc = _dict(net_total=80.0, taxes=[])
		rows = _tax_subtotals(doc)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["tax_percent"], 0)
		self.assertEqual(rows[0]["taxable_amount"], 80.0)

	def test_zero_rate_uses_net_total(self):
		doc = _dict(net_total=50.0, taxes=[_dict(rate=0, tax_amount=0)])
		rows = _tax_subtotals(doc)
		self.assertEqual(rows[0]["taxable_amount"], 50.0)
