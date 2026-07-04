# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from etransactions.plateforme_agreee.own_directory import _get_directory_client


class _FakePlatformDoc:
	"""Stand-in for an eTransactions Accredited Platform document."""

	def __init__(self, auth_method="client_credentials", client_secret="secret"):
		self.platform_type = "SuperPDP"
		self.api_base_url = None
		self.platform_code = "superpdp"
		self.is_sandbox = 1
		self._auth_method = auth_method
		self._client_secret = client_secret

	def get(self, key, default=None):
		if key == "auth_method":
			return self._auth_method
		return default

	def get_password(self, fieldname, raise_exception=True):
		if fieldname == "client_id":
			return "client-id"
		if fieldname == "client_secret":
			if self._client_secret is None and raise_exception:
				raise frappe.ValidationError("no secret")
			return self._client_secret
		return None


class TestOwnDirectoryClientBuild(UnitTestCase):
	"""The directory dialog must build clients exactly like check_platform_health:
	forwarding auth_method/platform_name and tolerating public OAuth clients
	that have no stored client_secret."""

	def _build(self, doc):
		with (
			patch(
				"etransactions.plateforme_agreee.own_directory.frappe.get_cached_doc",
				return_value=doc,
			),
			patch("etransactions.plateforme_agreee.own_directory._build_client") as build,
		):
			_get_directory_client("SuperPDP - Test")
		return build

	def test_oauth_platform_forwards_auth_method_and_platform_name(self):
		doc = _FakePlatformDoc(auth_method="authorization_code", client_secret=None)
		build = self._build(doc)
		build.assert_called_once_with(
			"SuperPDP",
			"client-id",
			None,
			api_base_url=None,
			platform_code="superpdp",
			sandbox=True,
			auth_method="authorization_code",
			platform_name="SuperPDP - Test",
		)

	def test_missing_client_secret_does_not_raise(self):
		# A public OAuth client stores no secret; building the directory client
		# must not blow up on get_password.
		doc = _FakePlatformDoc(auth_method="authorization_code", client_secret=None)
		self._build(doc)  # would raise without raise_exception=False

	def test_client_credentials_default(self):
		doc = _FakePlatformDoc(auth_method=None)
		build = self._build(doc)
		self.assertEqual(build.call_args.kwargs["auth_method"], "client_credentials")

	def test_unsupported_platform_type_throws(self):
		doc = _FakePlatformDoc()
		doc.platform_type = "Esalink"
		with (
			patch(
				"etransactions.plateforme_agreee.own_directory.frappe.get_cached_doc",
				return_value=doc,
			),
			self.assertRaises(frappe.ValidationError),
		):
			_get_directory_client("Esalink - Test")
