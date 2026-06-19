import frappe
from frappe.database.sequence import set_next_val


def execute():
	"""Resync the autoincrement sequence for Supplier Invoice.

	The DocType was renamed from "Pending Purchase Invoice" via rename_doc, which
	renames the table but not its `_id_seq` sequence, leaving the sequence behind
	the table's existing rows and causing DuplicateEntryError on insert.
	"""
	if frappe.db.db_type == "sqlite":
		return
	if not frappe.db.table_exists("Supplier Invoice"):
		return

	max_name = frappe.db.sql("SELECT MAX(`name`) FROM `tabSupplier Invoice`")[0][0]
	if not max_name:
		return

	# is_val_used=True so the next generated value is max_name + 1
	set_next_val("Supplier Invoice", int(max_name), is_val_used=True)
