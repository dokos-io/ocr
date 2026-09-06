# Copyright (c) 2026, Dokos SAS and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from etransactions.controllers.item_catalog_matcher import get_item_catalog, match_item_from_catalog


def _catalog(*names):
	return [frappe._dict(item_code=name, item_name=name) for name in names]


class TestItemCatalogMatcher(FrappeTestCase):
	def test_shared_word_matches(self):
		catalog = _catalog("Digital storage", "Nom de Domaine")

		result = match_item_from_catalog("Amazon Simple Storage Service", catalog)

		self.assertEqual(result, "Digital storage")

	def test_two_unrelated_matches_are_not_conflated(self):
		# "Services Cloud" ties "Digital storage" on the single word "service(s)" shared with
		# this label — the guess must stay silent rather than pick one arbitrarily.
		catalog = _catalog("Digital storage", "Services Cloud")

		result = match_item_from_catalog("Amazon Simple Storage Service", catalog)

		self.assertIsNone(result)

	def test_no_shared_word_returns_none(self):
		catalog = _catalog("Digital storage", "Nom de Domaine")

		result = match_item_from_catalog("RISE-S | AMD Ryzen 7 9700X rental for 1 month", catalog)

		self.assertIsNone(result)

	def test_ambiguous_tie_returns_none(self):
		catalog = _catalog("Cloud Storage", "Cloud Backup")

		# Both catalog items overlap the label by exactly two words; too close to call.
		result = match_item_from_catalog("Backup Cloud Storage Service", catalog)

		self.assertIsNone(result)

	def test_accent_and_plural_insensitive(self):
		catalog = _catalog("Hébergement Serveurs")

		result = match_item_from_catalog("Hebergement Serveur mensuel", catalog)

		self.assertEqual(result, "Hébergement Serveurs")

	def test_blank_label_returns_none(self):
		self.assertIsNone(match_item_from_catalog("", _catalog("Services Cloud")))
		self.assertIsNone(match_item_from_catalog(None, _catalog("Services Cloud")))

	def test_get_item_catalog_excludes_disabled(self):
		suffix = frappe.generate_hash(length=6).upper()
		enabled = _make_item(f"_Test Enabled {suffix}")
		disabled = _make_item(f"_Test Disabled {suffix}", disabled=1)

		codes = {row.item_code for row in get_item_catalog()}

		self.assertIn(enabled.item_code, codes)
		self.assertNotIn(disabled.item_code, codes)


def _make_item(item_code, disabled=0):
	item = frappe.new_doc("Item")
	item.item_code = item_code
	item.item_name = item_code
	item.item_group = "All Item Groups"
	item.disabled = disabled
	item.insert(ignore_if_duplicate=True)
	return item
