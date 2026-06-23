# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from frappe.tests import UnitTestCase

from etransactions.plateforme_agreee.routing import (
	identifier_to_electronic_address,
	is_valid_eas_scheme,
	parse_directory_identifier,
)


class TestIdentifierParsing(UnitTestCase):
	"""Pure parsing of platform addressing identifiers — no DB access."""

	def test_peppol_siren(self):
		out = parse_directory_identifier("0225:853322915")
		self.assertEqual(out["siren"], "853322915")
		self.assertIsNone(out["siret"])
		self.assertEqual(out["line_type"], "siren")

	def test_peppol_siret(self):
		out = parse_directory_identifier("0225:85332291500012")
		self.assertEqual(out["siret"], "85332291500012")
		self.assertEqual(out["siren"], "853322915")
		self.assertEqual(out["line_type"], "siret")

	def test_ppf_siren_underscore_siret(self):
		out = parse_directory_identifier("853322915_85332291500012")
		self.assertEqual(out["siret"], "85332291500012")
		self.assertEqual(out["line_type"], "siret")

	def test_ppf_siren_underscore_nic(self):
		out = parse_directory_identifier("853322915_00012")
		self.assertEqual(out["siret"], "85332291500012")
		self.assertEqual(out["line_type"], "siret")

	def test_routing_suffix(self):
		out = parse_directory_identifier("853322915_SERVICE1")
		self.assertEqual(out["siren"], "853322915")
		self.assertEqual(out["routing_code"], "SERVICE1")
		self.assertEqual(out["line_type"], "routing_code")

	def test_empty(self):
		out = parse_directory_identifier("")
		self.assertEqual(out, {"siren": None, "siret": None, "routing_code": None, "line_type": None})

	def test_electronic_address_split(self):
		self.assertEqual(identifier_to_electronic_address("0225:853322915"), ("0225", "853322915"))
		self.assertEqual(identifier_to_electronic_address("853322915"), ("0225", "853322915"))
		self.assertEqual(identifier_to_electronic_address(""), ("", ""))


class TestEASScheme(UnitTestCase):
	"""BR-CL-25 guard: only CEF EAS codes are valid electronic-address schemes."""

	def test_valid_eas_codes(self):
		for code in ("0225", "0009", "0002", "9959", "EM"):
			self.assertTrue(is_valid_eas_scheme(code), code)
		# Tolerates surrounding whitespace from stored data.
		self.assertTrue(is_valid_eas_scheme(" 0225 "))

	def test_non_eas_codes_rejected(self):
		# 0242 (OpenPeppol SPIS) exists in the Peppol participant-scheme list this
		# app installs but is NOT a CEF EAS code — it must not pass.
		for code in ("0242", "0000", "ABCD"):
			self.assertFalse(is_valid_eas_scheme(code), code)

	def test_empty_is_not_valid(self):
		self.assertFalse(is_valid_eas_scheme(None))
		self.assertFalse(is_valid_eas_scheme(""))
