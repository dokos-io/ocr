# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import frappe

from etransactions.utils.files import copy_file_to_document

__all__ = ["copy_file_to_document", "get_files_for_document"]


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
