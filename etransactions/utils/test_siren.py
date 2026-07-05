# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

import unittest

from etransactions.utils.siren import (
	is_valid_siren,
	siren_from_vat,
	vat_matches_siren,
)


class TestSiren(unittest.TestCase):
	def test_valid_siren(self):
		self.assertTrue(is_valid_siren("853322915"))  # Luhn-valid
		self.assertTrue(is_valid_siren("853 322 915"))  # spaces tolerated

	def test_invalid_siren(self):
		self.assertFalse(is_valid_siren("127741217"))  # fails Luhn
		self.assertFalse(is_valid_siren("85332291"))  # too short
		self.assertFalse(is_valid_siren("8533229155"))  # too long
		self.assertFalse(is_valid_siren("85332291A"))  # non-digit
		self.assertFalse(is_valid_siren(""))
		self.assertFalse(is_valid_siren(None))
		self.assertFalse(is_valid_siren("000000001"))  # sandbox display number

	def test_siren_from_vat(self):
		self.assertEqual(siren_from_vat("FR47853322915"), "853322915")
		self.assertEqual(siren_from_vat("fr 47 853322915"), "853322915")
		self.assertIsNone(siren_from_vat("DE123456789"))  # non-French
		self.assertIsNone(siren_from_vat("FR4785332291"))  # too short
		self.assertIsNone(siren_from_vat(""))
		self.assertIsNone(siren_from_vat(None))

	def test_vat_matches_siren(self):
		self.assertTrue(vat_matches_siren("FR47853322915", "853322915"))
		# Wrong key but the embedded SIREN still matches (we don't check the key).
		self.assertTrue(vat_matches_siren("FR12853322915", "853322915"))
		self.assertFalse(vat_matches_siren("FR00111111111", "853322915"))
		# Nothing to contradict → consistent.
		self.assertTrue(vat_matches_siren("DE123456789", "853322915"))  # non-French VAT
		self.assertTrue(vat_matches_siren("", "853322915"))  # no VAT
		self.assertTrue(vat_matches_siren("FR47853322915", ""))  # no SIREN
