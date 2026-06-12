import frappe

from etransactions.tests.utils import eTransactionsTestSuite


class TestVATConfigurationWidget(eTransactionsTestSuite):
	def test_get_vat_configuration_status_shape(self):
		from etransactions.etransactions.api.widgets import get_vat_configuration_status

		data = get_vat_configuration_status()

		self.assertIn("categories", data)
		self.assertIn("configured", data)
		self.assertEqual(data["tool_route"], "/app/france-vat-migration-tool")

		check_keys = [check["key"] for check in data["checks"]]
		self.assertEqual(
			check_keys, ["tax_rules", "customers", "suppliers", "addresses", "item_groups"]
		)
		for check in data["checks"]:
			self.assertGreaterEqual(check["total"], check["complete"])
			self.assertEqual(check["missing"], check["total"] - check["complete"])
			self.assertTrue(0 <= check["pct"] <= 100)

	def test_tax_rule_check_counts_full_pairs_only(self):
		from etransactions.etransactions.api.widgets import get_vat_configuration_status

		category = frappe.new_doc("Tax Category")
		category.title = "_Test Widget Category"
		category.insert(ignore_if_duplicate=True)

		data = get_vat_configuration_status()
		tax_rule_check = next(check for check in data["checks"] if check["key"] == "tax_rules")
		# The new category has no Sales + Purchase rule pair yet
		self.assertGreaterEqual(tax_rule_check["missing"], 1)
