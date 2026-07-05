# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from etransactions.utils import sirene


class _FakeResponse:
	def __init__(self, payload=None, status=200):
		self._payload = payload or {}
		self.status_code = status

	def raise_for_status(self):
		if self.status_code >= 400:
			raise Exception(f"HTTP {self.status_code}")

	def json(self):
		return self._payload


class TestFrVatFromSiren(UnitTestCase):
	def test_known_sirens(self):
		# Dokos SAS: SIREN 824710776 → FR94824710776 (real-world pair).
		self.assertEqual(sirene.fr_vat_from_siren("824710776"), "FR94824710776")
		self.assertEqual(sirene.fr_vat_from_siren("315143296"), "FR00315143296")

	def test_invalid_input(self):
		self.assertIsNone(sirene.fr_vat_from_siren(None))
		self.assertIsNone(sirene.fr_vat_from_siren("12345"))
		self.assertIsNone(sirene.fr_vat_from_siren("ABCDEFGHI"))


class TestSireneSearch(UnitTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.cache().delete_value("sirene_search:dokos:8")

	def test_search_trims_results(self):
		payload = {
			"results": [
				{
					"nom_raison_sociale": "DOKOS",
					"siren": "824710776",
					"etat_administratif": "A",
					"libelle_activite_principale": "Édition de logiciels",
					"siege": {
						"siret": "82471077600034",
						"numero_voie": "12",
						"type_voie": "RUE",
						"libelle_voie": "DE LA PAIX",
						"code_postal": "75002",
						"libelle_commune": "PARIS",
					},
				}
			]
		}
		with patch(
			"etransactions.utils.sirene.requests.get", return_value=_FakeResponse(payload)
		):
			rows = sirene.search("dokos")
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row["siren"], "824710776")
		self.assertEqual(row["tax_id"], "FR94824710776")
		self.assertEqual(row["siret"], "82471077600034")
		self.assertEqual(row["address_line1"], "12 RUE DE LA PAIX")
		self.assertEqual(row["city"], "PARIS")
		self.assertTrue(row["active"])

	def test_search_caches(self):
		payload = {"results": []}
		with patch(
			"etransactions.utils.sirene.requests.get", return_value=_FakeResponse(payload)
		) as get:
			sirene.search("dokos")
			sirene.search("dokos")
		self.assertEqual(get.call_count, 1)

	def test_short_query_returns_empty(self):
		self.assertEqual(sirene.search("do"), [])

	def test_http_error_throws_clean_message(self):
		with (
			patch(
				"etransactions.utils.sirene.requests.get",
				return_value=_FakeResponse({}, status=503),
			),
			self.assertRaises(frappe.ValidationError),
		):
			sirene.search("unreachable-query")
