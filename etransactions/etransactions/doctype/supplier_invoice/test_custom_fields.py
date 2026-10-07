# Copyright (c) 2026, Dokos SAS and Contributors
# See license.txt

import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

from etransactions.etransactions.doctype.supplier_invoice.custom_fields import (
	DOCTYPE,
	SECTION,
	move_existing_custom_fields,
)
from etransactions.tests.utils import eTransactionsTestSuite


class TestSupplierInvoiceCustomFields(eTransactionsTestSuite):
	def setUp(self):
		self.created = []

	def tearDown(self):
		# Adding a custom field alters the table, which commits: undo it by hand.
		for fieldname in self.created:
			if name := frappe.db.get_value("Custom Field", {"dt": DOCTYPE, "fieldname": fieldname}):
				frappe.delete_doc("Custom Field", name, force=True)
		frappe.db.delete("Property Setter", {"doc_type": DOCTYPE, "property": "field_order"})
		frappe.db.commit()
		frappe.clear_cache(doctype=DOCTYPE)

	def add(self, fieldname, insert_after="supplier", fieldtype="Data"):
		self.created.append(fieldname)
		create_custom_field(
			DOCTYPE,
			{
				"fieldname": fieldname,
				"label": fieldname,
				"fieldtype": fieldtype,
				"insert_after": insert_after,
			},
		)
		frappe.clear_cache(doctype=DOCTYPE)

	def order(self):
		return [f.fieldname for f in frappe.get_meta(DOCTYPE).fields]

	def assert_in_section(self, fieldname):
		order = self.order()
		self.assertGreater(order.index(fieldname), order.index(SECTION))
		self.assertLess(order.index(fieldname), order.index("custom_fields_end"))

	def test_new_custom_field_goes_to_the_review_tab(self):
		self.add("si_test_cost_code")

		self.assert_in_section("si_test_cost_code")

	def test_custom_fields_keep_the_order_they_were_added_in(self):
		self.add("si_test_first")
		self.add("si_test_second", insert_after="bill_no")

		order = self.order()
		self.assertEqual(order.index("si_test_second"), order.index("si_test_first") + 1)

	def test_field_placed_after_a_custom_field_keeps_its_place(self):
		self.add("si_test_group", fieldtype="Section Break")
		self.add("si_test_in_group", insert_after="si_test_group")

		self.assertEqual(
			frappe.db.get_value(
				"Custom Field", {"dt": DOCTYPE, "fieldname": "si_test_in_group"}, "insert_after"
			),
			"si_test_group",
		)
		self.assert_in_section("si_test_in_group")

	def test_custom_section_break_stays_on_the_review_tab(self):
		"""Frappe moves a section break to the next section break, which used to be on another tab."""
		self.add("si_test_first_section", fieldtype="Section Break")

		self.assert_in_section("si_test_first_section")

	def test_existing_custom_fields_are_moved(self):
		self.add("si_test_existing")
		name = frappe.db.get_value("Custom Field", {"dt": DOCTYPE, "fieldname": "si_test_existing"})
		frappe.db.set_value("Custom Field", name, "insert_after", "bill_no")
		# A field order saved from Customize Form would pin it next to bill_no.
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": "DocType",
				"doc_type": DOCTYPE,
				"property": "field_order",
				"property_type": "Data",
				"value": json.dumps(["company", "supplier", "bill_no", "si_test_existing", "items"]),
			}
		).insert()
		frappe.clear_cache(doctype=DOCTYPE)

		move_existing_custom_fields()

		self.assert_in_section("si_test_existing")
		setter = frappe.db.get_value(
			"Property Setter", {"doc_type": DOCTYPE, "property": "field_order"}, "value"
		)
		self.assertNotIn("si_test_existing", json.loads(setter))
