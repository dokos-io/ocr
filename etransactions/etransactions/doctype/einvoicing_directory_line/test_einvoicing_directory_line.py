# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase
from unittest.mock import MagicMock

from etransactions.components.superpdp.models import DirectoryData, DirectoryLineData
from etransactions.plateforme_agreee.directory import _sync_customer_directory


EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = ["Customer", "eInvoicing Directory Line"]


class TestDirectorySync(IntegrationTestCase):
	"""Integration tests for _sync_customer_directory.

	Each test creates its own Customer (and optional pre-existing directory
	lines), runs the sync against a mock PA client, then asserts the resulting
	DB state.  All created records are cleaned up via addCleanup.
	"""

	# ------------------------------------------------------------------
	# Fixtures
	# ------------------------------------------------------------------

	def _make_customer(self, suffix, siren_number="", tax_id=""):
		"""Insert a minimal Customer and register a cleanup."""
		name = f"_Test PA Dir {suffix}"
		if frappe.db.exists("Customer", name):
			frappe.db.delete("eInvoicing Directory Line", {"customer": name})
			frappe.delete_doc("Customer", name, ignore_permissions=True, force=True)

		frappe.get_doc({
			"doctype": "Customer",
			"customer_name": name,
			"customer_group": "All Customer Groups",
			"territory": "All Territories",
		}).insert(ignore_permissions=True)

		updates = {}
		if siren_number is not None:
			updates["siren_number"] = siren_number
		if tax_id:
			updates["tax_id"] = tax_id
		if updates:
			frappe.db.set_value("Customer", name, updates)

		self.addCleanup(self._delete_customer, name)
		return name

	def _delete_customer(self, name):
		frappe.db.delete("eInvoicing Directory Line", {"customer": name})
		if frappe.db.exists("Customer", name):
			frappe.delete_doc("Customer", name, ignore_permissions=True, force=True)

	def _make_line(self, customer, identifier, line_status="active",
				   routing_code_name=None, commitment_required=0):
		"""Insert a pre-existing eInvoicing Directory Line."""
		return frappe.get_doc({
			"doctype": "eInvoicing Directory Line",
			"customer": customer,
			"identifier": identifier,
			"line_status": line_status,
			"routing_code_name": routing_code_name or identifier,
			"commitment_required": commitment_required,
		}).insert(ignore_permissions=True).name

	def _client(self, response):
		mock = MagicMock()
		mock.get_directory_for_siren.return_value = response
		return mock

	def _result(self):
		return {"new_count": 0, "updated_count": 0, "logs": []}

	# ------------------------------------------------------------------
	# SIREN field selection
	# ------------------------------------------------------------------

	def test_skips_when_no_siren(self):
		"""Customer with no siren_number → early return, PA client never called."""
		customer = self._make_customer("no-siren", siren_number="")
		client = MagicMock()
		result = self._result()

		_sync_customer_directory(customer, client, result)

		client.get_directory_for_siren.assert_not_called()
		self.assertTrue(any("SIREN" in msg for _, msg in result["logs"]))

	def test_uses_siren_number_not_tax_id(self):
		"""When both tax_id and siren_number are present, only siren_number is
		passed to the PA — tax_id (VAT number) must not reach the directory API."""
		customer = self._make_customer(
			"siren-vs-taxid", siren_number="123456789", tax_id="FR12123456789"
		)
		response = DirectoryData(entity_type="private", name="Test Co", closed=False, lines={})
		client = self._client(response)
		result = self._result()

		_sync_customer_directory(customer, client, result)

		client.get_directory_for_siren.assert_called_once_with("123456789")

	# ------------------------------------------------------------------
	# Customer field updates
	# ------------------------------------------------------------------

	def test_updates_customer_directory_fields(self):
		"""After a successful sync the Customer's directory_* fields reflect the PA response."""
		customer = self._make_customer("updates-fields", siren_number="123456789")
		response = DirectoryData(entity_type="private", name="Acme SAS", closed=False, lines={})
		result = self._result()

		_sync_customer_directory(customer, self._client(response), result)

		values = frappe.db.get_value(
			"Customer", customer,
			["directory_entity_type", "directory_name", "directory_siren", "directory_update_date"],
			as_dict=True,
		)
		self.assertEqual(values.directory_entity_type, "private")
		self.assertEqual(values.directory_name, "Acme SAS")
		self.assertEqual(values.directory_siren, "123456789")
		self.assertEqual(values.directory_update_date, frappe.utils.getdate())

	# ------------------------------------------------------------------
	# Line creation
	# ------------------------------------------------------------------

	def test_creates_new_directory_lines(self):
		"""Identifiers returned by the PA that don't exist locally are inserted."""
		customer = self._make_customer("creates-lines", siren_number="111222333")
		lines = {
			"0225:111222333": DirectoryLineData(
				line_status="active", routing_code_name="PPF", commitment_required=False
			),
			"FR:111222333": DirectoryLineData(
				line_status="inactive", routing_code_name="PEPPOL", commitment_required=True
			),
		}
		response = DirectoryData(entity_type="private", name="Foo SA", closed=False, lines=lines)
		result = self._result()

		_sync_customer_directory(customer, self._client(response), result)

		created = frappe.get_all(
			"eInvoicing Directory Line",
			filters={"customer": customer},
			fields=["identifier", "line_status", "routing_code_name", "commitment_required"],
		)
		by_id = {r.identifier: r for r in created}

		self.assertEqual(result["new_count"], 2)
		self.assertIn("0225:111222333", by_id)
		self.assertEqual(by_id["0225:111222333"].line_status, "active")
		self.assertEqual(by_id["0225:111222333"].routing_code_name, "PPF")
		self.assertIn("FR:111222333", by_id)
		self.assertEqual(by_id["FR:111222333"].commitment_required, 1)

	# ------------------------------------------------------------------
	# Line updates
	# ------------------------------------------------------------------

	def test_updates_changed_lines(self):
		"""An existing line whose fields differ from the PA response is updated."""
		customer = self._make_customer("updates-lines", siren_number="222333444")
		self._make_line(customer, "0225:222333444", line_status="inactive", routing_code_name="OLD")
		response = DirectoryData(
			entity_type="private",
			name="Bar SAS",
			closed=False,
			lines={"0225:222333444": DirectoryLineData(line_status="active", routing_code_name="NEW")},
		)
		result = self._result()

		_sync_customer_directory(customer, self._client(response), result)

		row = frappe.db.get_value(
			"eInvoicing Directory Line",
			{"customer": customer, "identifier": "0225:222333444"},
			["line_status", "routing_code_name"],
			as_dict=True,
		)
		self.assertEqual(row.line_status, "active")
		self.assertEqual(row.routing_code_name, "NEW")
		self.assertEqual(result["updated_count"], 1)
		self.assertEqual(result["new_count"], 0)

	def test_skips_unchanged_lines(self):
		"""An existing line whose fields already match the PA response is left untouched."""
		customer = self._make_customer("skips-unchanged", siren_number="333444555")
		self._make_line(customer, "0225:333444555", line_status="active", routing_code_name="SAME")
		response = DirectoryData(
			entity_type="private",
			name="Baz SA",
			closed=False,
			lines={"0225:333444555": DirectoryLineData(line_status="active", routing_code_name="SAME")},
		)
		result = self._result()

		_sync_customer_directory(customer, self._client(response), result)

		self.assertEqual(result["updated_count"], 0)
		self.assertEqual(result["new_count"], 0)

	# ------------------------------------------------------------------
	# Line disabling — vanished identifiers
	# ------------------------------------------------------------------

	def test_disables_vanished_lines(self):
		"""A line that exists locally but is absent from the PA response is disabled."""
		customer = self._make_customer("disables-vanished", siren_number="444555666")
		self._make_line(customer, "OLD:444555666", line_status="active")
		response = DirectoryData(
			entity_type="private",
			name="Qux SAS",
			closed=False,
			lines={"NEW:444555666": DirectoryLineData(line_status="active", routing_code_name="NEW")},
		)
		result = self._result()

		_sync_customer_directory(customer, self._client(response), result)

		old_status = frappe.db.get_value(
			"eInvoicing Directory Line",
			{"customer": customer, "identifier": "OLD:444555666"},
			"line_status",
		)
		self.assertEqual(old_status, "disabled")
		self.assertEqual(result["updated_count"], 1)

	def test_already_disabled_lines_not_recounted(self):
		"""A line that was already disabled before the sync is not counted as updated."""
		customer = self._make_customer("already-disabled", siren_number="445566778")
		self._make_line(customer, "OLD:445566778", line_status="disabled")
		response = DirectoryData(
			entity_type="private",
			name="Quux SA",
			closed=False,
			lines={"NEW:445566778": DirectoryLineData(line_status="active", routing_code_name="NEW")},
		)
		result = self._result()

		_sync_customer_directory(customer, self._client(response), result)

		# The OLD line was already disabled, so updated_count should only
		# reflect the newly created line — not the pre-disabled one.
		self.assertEqual(result["new_count"], 1)
		self.assertEqual(result["updated_count"], 0)

	# ------------------------------------------------------------------
	# Line disabling — entity not in directory / closed
	# ------------------------------------------------------------------

	def test_disables_all_lines_when_not_in_directory(self):
		"""entity_type='no' → all existing active lines are disabled, no lines created."""
		customer = self._make_customer("not-in-dir", siren_number="555666777")
		self._make_line(customer, "0225:555666777", line_status="active")
		response = DirectoryData(entity_type="no", name="", closed=False)
		result = self._result()

		_sync_customer_directory(customer, self._client(response), result)

		status = frappe.db.get_value(
			"eInvoicing Directory Line",
			{"customer": customer, "identifier": "0225:555666777"},
			"line_status",
		)
		self.assertEqual(status, "disabled")
		self.assertEqual(result["new_count"], 0)

	def test_disables_all_lines_when_closed(self):
		"""closed=True → existing lines are disabled even if entity_type is known."""
		customer = self._make_customer("closed", siren_number="666777888")
		self._make_line(customer, "0225:666777888", line_status="active")
		response = DirectoryData(entity_type="private", name="Gone SA", closed=True)
		result = self._result()

		_sync_customer_directory(customer, self._client(response), result)

		status = frappe.db.get_value(
			"eInvoicing Directory Line",
			{"customer": customer, "identifier": "0225:666777888"},
			"line_status",
		)
		self.assertEqual(status, "disabled")
		# Customer fields are still written before the early return
		entity_type = frappe.db.get_value("Customer", customer, "directory_entity_type")
		self.assertEqual(entity_type, "private")
