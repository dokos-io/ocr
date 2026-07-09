# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe


def copy_file_to_document(file_name: str, attached_to_doctype: str, attached_to_name: str) -> str:
	"""Attach a copy of an existing File to another document and return the new File name.

	The original File record is left untouched so the source document keeps its audit trail.
	"""
	original_file = frappe.get_doc("File", file_name)
	new_file = frappe.copy_doc(original_file)
	new_file.attached_to_doctype = attached_to_doctype
	new_file.attached_to_name = attached_to_name
	new_file.attached_to_field = None
	new_file.insert(ignore_permissions=True)
	return new_file.name
