# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe


def get_files_for_document(doctype: str, name: str, file_types: list[str] | None = None) -> list[dict]:
	"""Return the File records attached to a document, including the ones
	attached to its linked Communications (inbound emails)."""
	filters: dict = {"attached_to_doctype": doctype, "attached_to_name": name}
	if file_types:
		filters["file_type"] = ("in", file_types)

	files = frappe.get_all("File", filters=filters, fields=["name", "file_name", "file_url"])

	communications = frappe.get_all(
		"Communication",
		filters={"reference_doctype": doctype, "reference_name": name},
		pluck="name",
	)
	for communication in communications:
		communication_filters: dict = {
			"attached_to_doctype": "Communication",
			"attached_to_name": communication,
		}
		if file_types:
			communication_filters["file_type"] = ("in", file_types)

		files.extend(
			frappe.get_all(
				"File",
				filters=communication_filters,
				fields=["name", "file_name", "file_url"],
			)
		)

	return files


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
