import frappe

from etransactions.tests.utils import eTransactionsTestSuite


class TestVATConfigurationWidget(eTransactionsTestSuite):
	def test_get_vat_configuration_status_shape(self):
		from etransactions.etransactions.api.widgets import get_vat_configuration_status

		data = get_vat_configuration_status()

		self.assertIn("categories", data)
		self.assertIn("configured", data)
		self.assertEqual(data["tool_route"], "/app/vat-configuration-tool")

		check_keys = [check["key"] for check in data["checks"]]
		self.assertEqual(
			check_keys, ["determination", "customers", "suppliers", "addresses", "item_groups"]
		)
		for check in data["checks"]:
			self.assertGreaterEqual(check["total"], check["complete"])
			self.assertEqual(check["missing"], check["total"] - check["complete"])
			self.assertTrue(0 <= check["pct"] <= 100)

	def test_determination_check_counts_rules_and_tagged_templates(self):
		from etransactions.etransactions.api.widgets import _determination_check

		category = frappe.new_doc("Tax Category")
		category.title = "_Test Widget Category"
		category.insert(ignore_if_duplicate=True)

		# Neither a Tax Rule nor a tagged template yet
		self.assertEqual(_determination_check([category.name])["complete"], 0)

		account = self._make_tax_account()
		sales_template = self._make_taxes_template(
			"Sales Taxes and Charges Template", "_Test Widget Determination Sales", account
		)
		frappe.db.set_value(
			"Sales Taxes and Charges Template", sales_template, "tax_category", category.name
		)
		# The Purchase side is still uncovered
		self.assertEqual(_determination_check([category.name])["complete"], 0)

		purchase_template = self._make_taxes_template(
			"Purchase Taxes and Charges Template", "_Test Widget Determination Purchase", account
		)
		tax_rule = frappe.new_doc("Tax Rule")
		tax_rule.tax_type = "Purchase"
		tax_rule.purchase_tax_template = purchase_template
		tax_rule.tax_category = category.name
		tax_rule.company = "_Test Company"
		tax_rule.insert()
		# The webshop may promote the first rule to a shopping cart rule
		frappe.db.set_value("Tax Rule", tax_rule.name, "use_for_shopping_cart", 0)

		# Tagged sales template + purchase Tax Rule cover both sides
		self.assertEqual(_determination_check([category.name])["complete"], 1)

	def _make_tax_account(self) -> str:
		existing = frappe.db.exists(
			"Account", {"account_name": "_Test Widget VAT", "company": "_Test Company"}
		)
		if existing:
			return existing
		account = frappe.new_doc("Account")
		account.account_name = "_Test Widget VAT"
		account.account_type = "Tax"
		account.parent_account = "Duties and Taxes - _TC"
		account.company = "_Test Company"
		account.insert()
		return account.name

	def _make_taxes_template(self, doctype: str, title: str, account: str) -> str:
		existing = frappe.db.exists(doctype, {"title": title, "company": "_Test Company"})
		if existing:
			return existing
		template = frappe.new_doc(doctype)
		template.title = title
		template.company = "_Test Company"
		row = {
			"charge_type": "On Net Total",
			"account_head": account,
			"rate": 20,
			"description": title,
		}
		if doctype == "Purchase Taxes and Charges Template":
			row["category"] = "Total"
			row["add_deduct_tax"] = "Add"
		template.append("taxes", row)
		template.insert()
		return template.name
