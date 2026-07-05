# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from etransactions.plateforme_agreee import session


def _client_ok() -> MagicMock:
	c = MagicMock()
	c.healthcheck.return_value = None
	return c


def _client_bad() -> MagicMock:
	"""A client whose auth probe fails, as a stale-credentials 401 would."""
	c = MagicMock()
	c.healthcheck.side_effect = frappe.ValidationError("boom: invalid_client")
	return c


class TestGetDirectoryClient(UnitTestCase):
	"""get_directory_client tolerates the company's own PA being unavailable and
	falls back to the first other active platform for read-only directory lookups."""

	def test_falls_back_to_first_active_when_company_has_none(self):
		ok = _client_ok()
		with patch.object(session, "get_platform_for_context", return_value=None), patch.object(
			frappe, "get_all", return_value=["PLAT-B"]
		), patch.object(session, "build_client_for_platform", return_value=ok) as build:
			client, used = session.get_directory_client("Co A")
		self.assertIs(client, ok)
		self.assertEqual(used, "PLAT-B")
		build.assert_called_once_with("PLAT-B")

	def test_skips_primary_that_fails_auth(self):
		bad, ok = _client_bad(), _client_ok()

		def build(name):
			return bad if name == "PLAT-A" else ok

		with patch.object(session, "get_platform_for_context", return_value="PLAT-A"), patch.object(
			frappe, "get_all", return_value=["PLAT-A", "PLAT-B"]
		), patch.object(session, "build_client_for_platform", side_effect=build):
			client, used = session.get_directory_client("Co A")
		# The primary 401'd on healthcheck, so the next active platform served the read.
		self.assertIs(client, ok)
		self.assertEqual(used, "PLAT-B")

	def test_primary_used_when_healthy(self):
		ok = _client_ok()
		with patch.object(session, "get_platform_for_context", return_value="PLAT-A"), patch.object(
			frappe, "get_all", return_value=["PLAT-A", "PLAT-B"]
		), patch.object(session, "build_client_for_platform", return_value=ok) as build:
			client, used = session.get_directory_client("Co A")
		self.assertEqual(used, "PLAT-A")
		build.assert_called_once_with("PLAT-A")

	def test_raises_when_no_active_platform(self):
		with patch.object(session, "get_platform_for_context", return_value=None), patch.object(
			frappe, "get_all", return_value=[]
		):
			with self.assertRaises(frappe.ValidationError):
				session.get_directory_client("Co A")

	def test_raises_when_all_candidates_fail(self):
		with patch.object(session, "get_platform_for_context", return_value="PLAT-A"), patch.object(
			frappe, "get_all", return_value=["PLAT-A"]
		), patch.object(session, "build_client_for_platform", return_value=_client_bad()):
			with self.assertRaises(frappe.ValidationError):
				session.get_directory_client("Co A")


class TestGetClientNoFallback(UnitTestCase):
	"""get_client (the send/e-reporting path) must stay strict — no cross-company fallback."""

	def test_get_client_does_not_fall_back(self):
		# No platform for the company -> throw; never consult other companies' platforms.
		with patch.object(session, "get_platform_for_context", return_value=None), patch.object(
			session, "build_client_for_platform"
		) as build:
			with self.assertRaises(frappe.ValidationError):
				session.get_client("Co A")
		build.assert_not_called()
