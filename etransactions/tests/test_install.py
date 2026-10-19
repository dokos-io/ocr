import unittest
import unittest.mock

from etransactions.install import _for_installed_erpnext


class FakeMeta:
	def __init__(self, fieldnames):
		self.fields = [unittest.mock.Mock(fieldname=fieldname) for fieldname in fieldnames]

	def has_field(self, fieldname):
		return any(df.fieldname == fieldname for df in self.fields)


class TestForInstalledERPNext(unittest.TestCase):
	def _adapt(self, custom_fields, metas):
		with unittest.mock.patch("frappe.get_meta", side_effect=lambda doctype: metas[doctype]):
			return _for_installed_erpnext(custom_fields)

	def test_dokos_fields_are_unchanged(self):
		custom_fields = {"Company": [{"fieldname": "etransactions_tab", "insert_after": "connections_tab"}]}
		metas = {"Company": FakeMeta(["tax_id", "siren_number", "connections_tab"])}

		self.assertEqual(self._adapt(custom_fields, metas), custom_fields)

	def test_siren_number_is_added_when_missing(self):
		metas = {"Company": FakeMeta(["tax_id", "dashboard_tab"])}

		company_fields = self._adapt({}, metas)["Company"]

		self.assertEqual(company_fields[0]["fieldname"], "siren_number")
		self.assertEqual(company_fields[0]["insert_after"], "tax_id")

	def test_missing_anchor_goes_after_the_last_field(self):
		custom_fields = {
			"Address": [
				{"fieldname": "etransactions_tab", "insert_after": "map_location"},
				{"fieldname": "siret_number", "insert_after": "etransactions_tab"},
			]
		}
		metas = {
			"Address": FakeMeta(["address_line1", "links", "etransactions_tab", "siret_number"]),
			"Company": FakeMeta(["tax_id", "siren_number"]),
		}

		address_fields = self._adapt(custom_fields, metas)["Address"]

		self.assertEqual(address_fields[0]["insert_after"], "links")
		self.assertEqual(address_fields[1]["insert_after"], "etransactions_tab")
