# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

from itertools import takewhile

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.desk.search import search_widget

from etransactions.install import add_custom_fields
from etransactions.overrides.custom_fields import CUSTOM_FIELDS
from etransactions.overrides.master_data import eas_scheme_query
from etransactions.tests.utils import eTransactionsTestSuite

EAS_SCHEME_QUERY = "etransactions.overrides.master_data.eas_scheme_query"


class TestEASSchemeQuery(eTransactionsTestSuite):
	"""The picker bound to ``etransactions_electronic_address_scheme``.

	Common Code is hash-named, and the framework reuses this very query to validate
	the value the user picked, calling it with ``txt = <docname>``. A query that
	could not find a record by its own name made the Link control clear the field
	right after selection (issue #8).
	"""

	def _common_code(self, code: str, title: str) -> str:
		existing = frappe.db.get_value("Common Code", {"common_code": code})
		if existing:
			return existing

		code_list = frappe.db.get_value("Code List", {}, "name") or frappe.get_doc({
			"doctype": "Code List",
			"__newname": "_Test Code List",
			"title": "_Test Code List",
			"version": "1",
		}).insert(ignore_permissions=True).name

		return frappe.get_doc({
			"doctype": "Common Code",
			"code_list": code_list,
			"common_code": code,
			"title": title,
		}).insert(ignore_permissions=True).name

	def _rows(self, txt: str) -> list:
		return eas_scheme_query("Common Code", txt, "name", 0, 20, None)

	def test_picker_finds_a_scheme_by_code_and_by_title(self):
		name = self._common_code("0225", "FRCTC Electronic Address")

		self.assertIn(name, [row[0] for row in self._rows("0225")])
		self.assertIn(name, [row[0] for row in self._rows("FRCTC")])

	def test_picker_hides_non_eas_schemes(self):
		# 0242 (Peppol SPIS) is a valid participant-identifier scheme but not part
		# of the CEF EAS code list, so an invoice addressed with it fails BR-CL-25.
		name = self._common_code("0242", "SPIS")

		self.assertNotIn(name, [row[0] for row in self._rows("0242")])

	def test_link_validation_resolves_the_hash_docname(self):
		"""The regression: validating the picked value must not come back empty."""
		name = self._common_code("0225", "FRCTC Electronic Address")

		results = search_widget(
			doctype="Common Code",
			txt=name,
			query=EAS_SCHEME_QUERY,
			as_dict=False,
			page_length=20,
			for_link_validation=True,
		)

		self.assertTrue(results, "link validation found no record for the picked scheme")
		self.assertIn(name, [row[0] for row in results])


class TestETransactionsTabs(eTransactionsTestSuite):
	"""An eTransactions tab is hidden while e-invoicing is off, and a Tab Break takes
	every field after it up to the next one. Anchored mid-form, the Address tab hid
	its linked documents, checkboxes and map on every site without e-invoicing.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Mirrors erpnext's France setup, whose siret_number was the tab's old anchor
		create_custom_field(
			"Address", {"fieldname": "siret_number", "fieldtype": "Data", "insert_after": "fax"}
		)
		add_custom_fields()

	def test_tabs_hold_only_etransactions_fields(self):
		for doctype, fields in CUSTOM_FIELDS.items():
			own_fieldnames = {df["fieldname"] for df in fields}

			for tab in (df for df in fields if df["fieldtype"] == "Tab Break"):
				with self.subTest(doctype=doctype, tab=tab["fieldname"]):
					foreign_fields = self._fieldnames_in_tab(doctype, tab["fieldname"]) - own_fieldnames
					self.assertFalse(foreign_fields, f"{doctype} fields caught in {tab['fieldname']}")

	def _fieldnames_in_tab(self, doctype: str, tab_fieldname: str) -> set[str]:
		fields = frappe.get_meta(doctype).fields
		tab_index = next(i for i, df in enumerate(fields) if df.fieldname == tab_fieldname)
		fields_until_next_tab = takewhile(lambda df: df.fieldtype != "Tab Break", fields[tab_index + 1 :])
		return {df.fieldname for df in fields_until_next_tab}
