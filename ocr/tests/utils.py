from random import choice, randint
from erpnext import get_default_company
from erpnext.accounts.doctype.item_tax_template.item_tax_template import ItemTaxTemplate
from erpnext.buying.doctype.supplier.supplier import Supplier
from faker import Faker
import frappe

from erpnext.stock.doctype.item.item import Item

def add_items():
	if frappe.get_all("Item"):
		return

	item_tax_template: ItemTaxTemplate = frappe.new_doc("Item Tax Template") # type: ignore
	item_tax_template.title = "TVA 20% Collectée"
	item_tax_template.company = get_default_company() # type: ignore
	item_tax_template.applicable_for = "Purchases" # type: ignore
	item_tax_template.append("taxes", {
		"tax_type": frappe.db.get_value("Account", dict(account_type="Tax")),
		"tax_rate": 20.0,
		"description": "TVA 20%"
	})
	item_tax_template.insert(ignore_if_duplicate=True)

	item_groups = frappe.get_all("Item Group", filters={"is_group": 0})
	for item_group in item_groups:
		for i in range(randint(2, 6)):
			item: Item = frappe.new_doc("Item") # type: ignore
			item.item_group = item_group.name
			item.item_code = frappe.generate_hash(length=10)
			item.item_name = f"{item_group.name}: Test Item {i}"
			item.is_stock_item = False
			item.stock_uom = "Unit"
			item.append("taxes", {
				"item_tax_template": item_tax_template.name 
			})
			item.insert(ignore_if_duplicate=True)


def add_suppliers():
	if frappe.get_all("Supplier"):
		return

	fake = Faker("fr_FR")
	supplier_groups = frappe.get_all("Supplier Group", filters={"is_group": 0}, pluck="name")
	for _i in range(50):
		supplier: Supplier = frappe.new_doc("Supplier") # type: ignore
		supplier.supplier_name = fake.unique.company()
		supplier.supplier_type = "Company"
		supplier.supplier_group = choice(supplier_groups)
		supplier.insert()