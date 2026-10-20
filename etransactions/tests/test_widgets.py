from unittest.mock import patch

import frappe

from etransactions.plateforme_agreee import item_tax_coverage
from etransactions.plateforme_agreee.item_tax_coverage import ItemTaxResolver, required_pairs
from etransactions.tests.utils import eTransactionsTestSuite

COMPANY = "_Test Company"
EXPORT = "_Test Widget Export"


def _make_tax_account() -> str:
	existing = frappe.db.exists("Account", {"account_name": "_Test Widget VAT", "company": "_Test Company"})
	if existing:
		return existing
	account = frappe.new_doc("Account")
	account.account_name = "_Test Widget VAT"
	account.account_type = "Tax"
	account.parent_account = "Duties and Taxes - _TC"
	account.company = "_Test Company"
	account.insert()
	return account.name


class TestVATConfigurationWidget(eTransactionsTestSuite):
	def test_get_vat_configuration_status_shape(self):
		from etransactions.etransactions.api.widgets import get_vat_configuration_status

		data = get_vat_configuration_status()

		self.assertIn("categories", data)
		self.assertIn("configured", data)
		self.assertEqual(data["tool_route"], "/app/vat-configuration-tool")

		check_keys = [check["key"] for check in data["checks"]]
		self.assertEqual(check_keys, ["determination", "customers", "suppliers", "addresses", "item_groups"])
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

		account = _make_tax_account()
		sales_template = self._make_taxes_template(
			"Sales Taxes and Charges Template", "_Test Widget Determination Sales", account
		)
		frappe.db.set_value("Sales Taxes and Charges Template", sales_template, "tax_category", category.name)
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


class TestItemTaxCoverage(eTransactionsTestSuite):
	"""Coverage follows ERPNext: item rows, then the item group, then its ancestors."""

	def setUp(self):
		super().setUp()
		category = frappe.new_doc("Tax Category")
		category.title = EXPORT
		category.insert(ignore_if_duplicate=True)

		account = _make_tax_account()
		self.domestic_template = self._make_item_tax_template("_Test Widget VAT 20", account)
		self.export_template = self._make_item_tax_template("_Test Widget VAT 0", account)
		self.required = frozenset({("", COMPANY), (EXPORT, COMPANY)})

		self.parent_group = self._make_item_group("_Test Widget Parent Group", "All Item Groups")
		self.child_group = self._make_item_group("_Test Widget Child Group", self.parent_group)

	def test_item_inherits_rows_from_its_group(self):
		self._set_rows("Item Group", self.child_group, self._full_rows())
		item = self._make_item("_Test Widget Item Group Rows", self.child_group)

		status = ItemTaxResolver().item_status(item, self.child_group, None, self.required)

		self.assertTrue(status.is_ready)

	def test_item_inherits_rows_from_an_ancestor_group(self):
		self._set_rows("Item Group", self.parent_group, self._full_rows())
		item = self._make_item("_Test Widget Item Ancestor Rows", self.child_group)

		resolver = ItemTaxResolver()

		self.assertTrue(resolver.item_status(item, self.child_group, None, self.required).is_ready)
		self.assertTrue(resolver.group_covers(self.child_group, self.required))

	def test_own_rows_fall_back_to_the_group_per_category(self):
		self._set_rows("Item Group", self.parent_group, self._full_rows())
		item = self._make_item(
			"_Test Widget Item Own Domestic Row",
			self.child_group,
			rows=[{"item_tax_template": self.domestic_template}],
		)

		status = ItemTaxResolver().item_status(item, self.child_group, None, self.required)

		self.assertTrue(status.full_coverage)

	def test_missing_domestic_row_is_not_covered(self):
		self._set_rows(
			"Item Group",
			self.child_group,
			[{"item_tax_template": self.export_template, "tax_category": EXPORT}],
		)
		item = self._make_item("_Test Widget Item No Domestic Row", self.child_group)

		resolver = ItemTaxResolver()

		self.assertFalse(resolver.item_status(item, self.child_group, None, self.required).full_coverage)
		self.assertFalse(resolver.group_covers(self.child_group, self.required))

	def test_disabled_and_purchase_templates_do_not_cover(self):
		self._set_rows("Item Group", self.child_group, self._full_rows())
		frappe.db.set_value("Item Tax Template", self.domestic_template, "disabled", 1)
		self.assertFalse(ItemTaxResolver().group_covers(self.child_group, self.required))

		frappe.db.set_value("Item Tax Template", self.domestic_template, "disabled", 0)
		frappe.db.set_value("Item Tax Template", self.domestic_template, "applicable_for", "Purchases")
		self.assertFalse(ItemTaxResolver().group_covers(self.child_group, self.required))

	def test_only_french_companies_are_required(self):
		companies = [
			frappe._dict(name="French Co", country="France"),
			frappe._dict(name="Moroccan Co", country="Morocco"),
		]
		with patch.object(item_tax_coverage.frappe, "get_all", return_value=companies):
			pairs = required_pairs({EXPORT})

		self.assertEqual(pairs, frozenset({("", "French Co"), (EXPORT, "French Co")}))

	def test_all_companies_are_required_when_none_is_french(self):
		companies = [frappe._dict(name="Moroccan Co", country="Morocco")]
		with patch.object(item_tax_coverage.frappe, "get_all", return_value=companies):
			self.assertEqual(required_pairs(set()), frozenset({("", "Moroccan Co")}))

	def _full_rows(self) -> list[dict]:
		return [
			{"item_tax_template": self.domestic_template},
			{"item_tax_template": self.export_template, "tax_category": EXPORT},
		]

	def _set_rows(self, doctype: str, name: str, rows: list[dict]) -> None:
		doc = frappe.get_doc(doctype, name)
		doc.set("taxes", rows)
		doc.save()

	def _make_item_tax_template(self, title: str, account: str) -> str:
		existing = frappe.db.exists("Item Tax Template", {"title": title, "company": COMPANY})
		if existing:
			frappe.db.set_value("Item Tax Template", existing, {"disabled": 0, "applicable_for": ""})
			return existing
		template = frappe.new_doc("Item Tax Template")
		template.title = title
		template.company = COMPANY
		template.append("taxes", {"tax_type": account, "tax_rate": 20})
		template.insert()
		return template.name

	def _make_item_group(self, name: str, parent: str) -> str:
		if not frappe.db.exists("Item Group", name):
			group = frappe.new_doc("Item Group")
			group.item_group_name = name
			group.parent_item_group = parent
			group.is_group = 1
			group.insert()
		self._set_rows("Item Group", name, [])
		return name

	def _make_item(self, code: str, item_group: str, rows: list[dict] | None = None) -> str:
		if frappe.db.exists("Item", code):
			frappe.delete_doc("Item", code, force=True)
		item = frappe.new_doc("Item")
		item.item_code = code
		item.item_group = item_group
		item.stock_uom = "Nos"
		item.is_stock_item = 0
		item.set("taxes", rows or [])
		item.insert()
		return item.name
