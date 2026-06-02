# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from frappe.tests import UnitTestCase

from etransactions.plateforme_agreee import lifecycle_status as ls


class TestLifecycleStatus(UnitTestCase):
	"""Pure-logic tests for the canonical lifecycle status registry and mappings.

	No database access — safe and fast to run in isolation.
	"""

	def test_every_status_has_required_fields(self):
		for status, vals in ls.STATUSES.items():
			self.assertIn(status, ls.LABELS, f"missing label for {status}")
			self.assertTrue(vals.get("mdt105"), f"missing MDT-105 for {status}")

	def test_superpdp_roundtrip(self):
		# Only statuses with a SuperPDP code round-trip through the fr: codes.
		for status, vals in ls.STATUSES.items():
			code = vals.get("superpdp")
			if not code:
				continue
			self.assertEqual(ls.to_superpdp_code(status), code)
			self.assertEqual(ls.from_superpdp_code(code), status)

	def test_unsupported_superpdp_status_raises(self):
		# "refused" has no SuperPDP code yet and must raise rather than guess.
		self.assertIsNone(ls.STATUSES["refused"]["superpdp"])
		with self.assertRaises(Exception):
			ls.to_superpdp_code("refused")

	def test_cdar_roundtrip(self):
		for status in ls.STATUSES:
			mdt105, _mdt88 = ls.to_cdar_codes(status)
			self.assertEqual(ls.from_cdar_code(mdt105), status)

	def test_mdt105_codes_unique(self):
		codes = [v["mdt105"] for v in ls.STATUSES.values()]
		self.assertEqual(len(codes), len(set(codes)), "MDT-105 codes must be unique")

	def test_manual_statuses_partitioned_by_side(self):
		purchase = set(ls.manual_statuses("purchase"))
		sale = set(ls.manual_statuses("sale"))
		self.assertIn("refused", purchase)
		self.assertIn("payment_received", sale)
		self.assertFalse(purchase & sale, "a status cannot be manual for both sides")

	def test_warning_statuses(self):
		self.assertTrue(ls.is_warning("refused"))
		self.assertTrue(ls.is_warning("dispute"))
		self.assertFalse(ls.is_warning("approved"))
