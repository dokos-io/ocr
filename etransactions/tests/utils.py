from random import choice, randint
from erpnext import get_default_company
from erpnext.accounts.doctype.item_tax_template.item_tax_template import ItemTaxTemplate
from erpnext.buying.doctype.supplier.supplier import Supplier
from erpnext.tests.utils import ERPNextTestSuite
from faker import Faker
import frappe

from erpnext.stock.doctype.item.item import Item
from frappe.desk.page.setup_wizard.setup_wizard import setup_complete
from frappe.utils import now_datetime

def add_items():
	item_tax_template: ItemTaxTemplate = frappe.new_doc("Item Tax Template") # type: ignore
	item_tax_template.title = "TVA 20% Collectée"
	item_tax_template.company = get_default_company() # type: ignore
	item_tax_template.applicable_for = "Purchases" # type: ignore
	item_tax_template.append("taxes", {
		"tax_type": frappe.db.get_value("Account", dict(account_type="Tax", company=get_default_company())),
		"tax_rate": 20.0,
		"description": "TVA 20%"
	})
	item_tax_template.insert(ignore_if_duplicate=True)

	item_groups = frappe.get_all("Item Group", filters={"is_group": 0})
	items = []
	for item_group in item_groups:
		for i in range(randint(2, 6)):
			item: Item = frappe.new_doc("Item") # type: ignore
			item.item_group = item_group.name
			item.item_code = frappe.generate_hash(length=10)
			item.item_name = f"{item_group.name}: Test Item {i}"
			item.is_stock_item = False
			item.stock_uom = "Unit"
			item.append("taxes", {
				"item_tax_template": item_tax_template.name,
				"company": get_default_company()
			})
			item.insert(ignore_if_duplicate=True)
			items.append(item.name)

	return items


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



def minimal_pdf_content() -> bytes:
	"""Return the bytes of a minimal but structurally valid one-page PDF.

	Needed because File creation hooks parse PDF attachments with pypdf,
	which rejects arbitrary placeholder bytes.
	"""
	header = b"%PDF-1.4\n"
	objects = [
		b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
		b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n",
		b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n",
	]

	offsets = []
	body = b""
	position = len(header)
	for pdf_object in objects:
		offsets.append(position)
		body += pdf_object
		position += len(pdf_object)

	xref = b"xref\n0 4\n0000000000 65535 f \n"
	for offset in offsets:
		xref += f"{offset:010d} 00000 n \n".encode()

	trailer = (
		b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n" + str(position).encode() + b"\n%%EOF\n"
	)
	return header + body + xref + trailer


class eTransactionsTestSuite(ERPNextTestSuite):
	"""Base class for eTransactions integration test suites"""

	pass
