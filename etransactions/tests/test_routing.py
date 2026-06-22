# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from frappe.tests import UnitTestCase

from etransactions.plateforme_agreee.routing import (
	identifier_to_electronic_address,
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
