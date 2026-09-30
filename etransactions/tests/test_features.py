# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from etransactions.features import FEATURES, get_enabled_features, is_feature_enabled
from etransactions.plateforme_agreee.directory import get_address_routing, get_customer_routing
from etransactions.plateforme_agreee.readiness import _routing_findings, customer_check_specs
from etransactions.tests.utils import eTransactionsTestSuite

SETTINGS = "eTransactions Settings"


class FeatureSettingsMixin:
	"""Set eTransactions Settings flags for one test, restoring them afterwards."""

	def set_settings(self, **values):
		previous = {field: frappe.db.get_single_value(SETTINGS, field) for field in values}
		self.addCleanup(self._apply_settings, previous)
		self._apply_settings(values)

	def _apply_settings(self, values):
		for field, value in values.items():
			frappe.db.set_single_value(SETTINGS, field, value)
		frappe.clear_document_cache(SETTINGS, SETTINGS)

	def set_features(self, enabled=(), einvoicing=1):
		self.set_settings(
			enable_einvoicing=einvoicing,
			**{field: int(key in enabled) for key, field in FEATURES.items()},
		)


class TestFeatureFlags(FeatureSettingsMixin, eTransactionsTestSuite):
	def test_all_features_off_by_default(self):
		self.set_features()
		self.assertEqual(get_enabled_features(), dict.fromkeys(FEATURES, 0))

	def test_feature_follows_its_toggle(self):
		self.set_features(enabled=("peppol",))
		self.assertTrue(is_feature_enabled("peppol"))
		self.assertFalse(is_feature_enabled("public_sector"))

	def test_features_off_while_einvoicing_is_off(self):
		self.set_features(enabled=tuple(FEATURES), einvoicing=0)
		self.assertFalse(any(get_enabled_features().values()))

	def test_readiness_skips_checks_of_disabled_features(self):
		self.set_features()
		keys = {spec.key for spec in customer_check_specs()}
		self.assertNotIn("profile", keys)
		self.assertNotIn("peppol_directory_supported", keys)

		self.set_features(enabled=("peppol", "profile_choice"))
		keys = {spec.key for spec in customer_check_specs()}
		self.assertIn("profile", keys)
		self.assertIn("peppol_directory_supported", keys)


class TestSimpleModeDefaults(FeatureSettingsMixin, eTransactionsTestSuite):
	def _customer_group(self):
		return frappe.get_all("Customer Group", filters={"is_group": 0}, pluck="name")[0]

	def make_customer(self, suffix, **values):
		name = f"_Test Features {suffix}"
		if frappe.db.exists("Customer", name):
			frappe.delete_doc("Customer", name, ignore_permissions=True, force=True)
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_group": self._customer_group(),
				"territory": "All Territories",
			}
		).insert(ignore_permissions=True)
		if values:
			frappe.db.set_value("Customer", name, values)
		self.addCleanup(frappe.delete_doc, "Customer", name, ignore_permissions=True, force=True)
		return name

	def make_address(self, customer, suffix, siret):
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"_Test Features Addr {suffix}",
				"address_type": "Billing",
				"address_line1": "1 rue de la Paix",
				"city": "Paris",
				"country": "France",
				"siret_number": siret,
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Address", address.name, ignore_permissions=True, force=True)
		return address.name

	def make_line(self, customer, identifier, address=None):
		line = frappe.get_doc(
			{
				"doctype": "eInvoicing Directory Line",
				"customer": customer,
				"identifier": identifier,
				"line_status": "active",
				"address": address,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "eInvoicing Directory Line", line.name, ignore_permissions=True, force=True
		)
		return line.name

	def test_default_profile_applied_silently_without_profile_choice(self):
		from etransactions.overrides.master_data import (
			DEFAULT_PROFILE,
			apply_default_etransaction_profile,
		)

		if not frappe.db.exists("eTransaction Profile", DEFAULT_PROFILE):
			self.skipTest("EN16931 profile fixture missing")
		self.set_features()
		self.set_settings(default_etransaction_profile=None)
		doc = frappe._dict(siren_number="315143296", etransaction_profile=None, customer_primary_address=None)
		with patch("etransactions.overrides.master_data.frappe.msgprint") as msgprint:
			apply_default_etransaction_profile(doc)
		self.assertEqual(doc.etransaction_profile, DEFAULT_PROFILE)
		msgprint.assert_not_called()

	def test_invoice_gets_default_profile_without_profile_choice(self):
		from etransactions.overrides.master_data import DEFAULT_PROFILE
		from etransactions.overrides.sales_invoice import _apply_default_profile

		if not frappe.db.exists("eTransaction Profile", DEFAULT_PROFILE):
			self.skipTest("EN16931 profile fixture missing")
		self.set_features()
		self.set_settings(default_etransaction_profile=None)
		customer = self.make_customer("invoice profile", siren_number="315143296")
		doc = frappe._dict(customer=customer, customer_address=None, etransaction_profile=None)
		_apply_default_profile(doc)
		self.assertEqual(doc.etransaction_profile, DEFAULT_PROFILE)

		# With profile choice, the customer's own (empty) profile stays authoritative.
		self.set_features(enabled=("profile_choice",))
		doc = frappe._dict(customer=customer, customer_address=None, etransaction_profile=None)
		_apply_default_profile(doc)
		self.assertIsNone(doc.etransaction_profile)

	def test_customer_routing_single_address(self):
		customer = self.make_customer("single")
		line = self.make_line(customer, "315143296")
		routing = get_customer_routing(customer)
		self.assertEqual(routing["line"].name, line)
		self.assertFalse(routing["needs_default"])

	def test_customer_routing_per_siret(self):
		customer = self.make_customer("per siret")
		head_office = self.make_address(customer, "HQ", "31514329600010")
		branch = self.make_address(customer, "Branch", "31514329600028")
		self.make_line(customer, "315143296_31514329600010", address=head_office)

		# Several addresses and no default: the user must pick one.
		self.make_line(customer, "315143296")
		self.assertTrue(get_customer_routing(customer)["needs_default"])

		routing = get_customer_routing(customer, head_office)
		self.assertTrue(routing["own"])
		self.assertEqual(routing["line"].identifier, "315143296_31514329600010")

		# The branch has no line of its own and no default is chosen yet: unroutable.
		(branch_routing,) = get_address_routing(branch)
		self.assertIsNone(branch_routing["line"])

	def test_b2g_finding_points_to_settings_without_public_sector(self):
		self.set_features()
		customer = self.make_customer("public", directory_entity_type="public")
		doc = SimpleNamespace(
			company="_Test Company",
			customer=customer,
			get=lambda k, d=None: {
				"company": "_Test Company",
				"customer": customer,
				"customer_address": None,
				"etransactions_buyer_reference": None,
			}.get(k, d),
		)
		with (
			patch("etransactions.plateforme_agreee.session.get_platform_settings", return_value=True),
			patch("etransactions.plateforme_agreee.routing.resolve_routing", return_value=None),
		):
			findings = {f.key: f for f in _routing_findings(doc)}
		self.assertEqual(findings["b2g_service_code"].fix_doctype, SETTINGS)
		self.assertIsNone(findings["b2g_service_code"].fix_field)


class TestEnableFeaturesPatch(FeatureSettingsMixin, eTransactionsTestSuite):
	def test_features_in_use_are_enabled(self):
		from etransactions.patches.enable_einvoicing_features_if_used import execute

		self.set_features()
		group = frappe.get_all("Customer Group", filters={"is_group": 0}, pluck="name")[0]
		name = "_Test Features Patch"
		if frappe.db.exists("Customer", name):
			frappe.delete_doc("Customer", name, ignore_permissions=True, force=True)
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_group": group,
				"territory": "All Territories",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Customer", name, ignore_permissions=True, force=True)
		frappe.db.set_value("Customer", name, {"directory_pinned": 1, "directory_type": "peppol"})

		execute()
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		self.assertTrue(is_feature_enabled("advanced_routing"))
		self.assertTrue(is_feature_enabled("peppol"))
