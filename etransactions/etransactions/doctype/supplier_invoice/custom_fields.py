# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

"""Custom fields of a Supplier Invoice are shown on its Review tab.

The Review tab is where users work on an invoice, so the fields they add themselves (or
another app adds for them) belong there, in the "Additional Information" section at the
end of the tab. A custom field placed after another custom field keeps its place, so a
group of fields the user built (a section, columns, a tab) stays together.
"""

import json

import frappe

DOCTYPE = "Supplier Invoice"
SECTION = "custom_fields_section"


def place_in_review_tab(doc, method=None):
	"""Custom Field ``before_insert``: put a new Supplier Invoice field in the section."""
	if doc.dt != DOCTYPE or is_custom_field(doc.insert_after):
		return
	doc.insert_after = last_field_of_section(exclude=doc.fieldname)


def is_custom_field(fieldname: str | None) -> bool:
	return bool(fieldname) and bool(frappe.db.exists("Custom Field", {"dt": DOCTYPE, "fieldname": fieldname}))


def last_field_of_section(exclude: str | None = None) -> str:
	"""The field after which a new custom field goes, so fields keep the order they were added in."""
	fields = [f for f in frappe.get_meta(DOCTYPE).fields if f.fieldname != exclude]
	names = [f.fieldname for f in fields]
	if SECTION not in names:
		return SECTION
	last = SECTION
	for field in fields[names.index(SECTION) + 1 :]:
		if not field.get("is_custom_field"):
			break
		last = field.fieldname
	return last


def move_existing_custom_fields():
	"""Move the custom fields placed among the standard fields into the section."""
	custom_fields = frappe.get_all(
		"Custom Field",
		filters={"dt": DOCTYPE},
		fields=["name", "fieldname", "insert_after"],
		order_by="idx asc, creation asc",
	)
	custom = {f.fieldname for f in custom_fields}
	to_move = [f for f in custom_fields if f.insert_after not in custom]
	if not to_move:
		return

	# A field order saved from Customize Form would keep the fields where they are.
	moved = {f.fieldname for f in to_move}
	if setter := frappe.db.get_value(
		"Property Setter", {"doc_type": DOCTYPE, "property": "field_order"}, ["name", "value"], as_dict=True
	):
		order = [name for name in json.loads(setter.value or "[]") if name not in moved]
		frappe.db.set_value("Property Setter", setter.name, "value", json.dumps(order), update_modified=False)

	for field in to_move:
		# After the fields already moved, including the ones placed after them.
		frappe.clear_cache(doctype=DOCTYPE)
		anchor = last_field_of_section(exclude=field.fieldname)
		frappe.db.set_value("Custom Field", field.name, "insert_after", anchor, update_modified=False)
	frappe.clear_cache(doctype=DOCTYPE)
