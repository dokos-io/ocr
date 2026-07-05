# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import MagicMock, patch

from frappe.tests import UnitTestCase

from etransactions.components.esalink import (
	EsalinkClient,
	EsalinkPartnerClient,
	base_url_for_environment,
)
from etransactions.plateforme_agreee import esalink_provisioning as prov

BASE = "https://ppd.hubtimize.fr/api/orchestrator"


class _FakeResponse:
	"""Minimal stand-in for requests.Response."""

	def __init__(self, payload=None, content=b"x", status_code=200, text=""):
		self._payload = payload if payload is not None else {}
		self.content = content
		self.ok = status_code < 400
		self.status_code = status_code
		self.text = text

	def json(self):
		return self._payload


def _ops_client() -> EsalinkClient:
	c = EsalinkClient(
		username="cid", password="secret", api_key="key-123", base_url=BASE
	)
	c._access_token = "tok"
	c._token_expires_at = float("inf")
	return c


def _partner() -> EsalinkPartnerClient:
	c = EsalinkPartnerClient(
		username="puser", password="ppass", api_key="key-123", base_url=BASE
	)
	c._access_token = "tok"
	c._token_expires_at = float("inf")
	return c


class TestEsalinkTransport(UnitTestCase):
	def test_base_url_per_environment(self):
		self.assertEqual(
			base_url_for_environment("prod"), "https://hubtimize.fr/api/orchestrator"
		)
		self.assertEqual(base_url_for_environment("test"), BASE)
		self.assertEqual(base_url_for_environment(None), BASE)  # defaults to test

	def test_token_call_posts_json_with_api_key(self):
		client = EsalinkClient(
			username="cid", password="secret", api_key="key-123", base_url=BASE
		)
		fake = MagicMock()
		fake.post.return_value = _FakeResponse(
			{"access_token": "abc", "expires_in": 3600}
		)
		with patch("etransactions.components.esalink.client.requests", fake):
			client._fetch_token()
		url, kwargs = fake.post.call_args[0][0], fake.post.call_args[1]
		self.assertEqual(url, f"{BASE}/v1/token")
		self.assertEqual(kwargs["json"], {"username": "cid", "password": "secret"})
		self.assertEqual(kwargs["headers"], {"hubtimize-api-key": "key-123"})
		self.assertEqual(client._access_token, "abc")

	def test_headers_carry_bearer_and_api_key(self):
		h = _ops_client()._headers()
		self.assertEqual(h["Authorization"], "Bearer tok")
		self.assertEqual(h["hubtimize-api-key"], "key-123")

	def test_healthcheck_hits_v1_healthcheck(self):
		client = _ops_client()
		with patch.object(client, "_request", return_value=_FakeResponse()) as req:
			client.healthcheck()
		self.assertEqual(req.call_args[0], ("GET", "/v1/healthcheck"))

	def test_token_path_overrides_afnor(self):
		# Operations client must use /v1/token, not AFNOR's /v1/oauth2/token.
		self.assertEqual(EsalinkClient._TOKEN_PATH, "/v1/token")


class TestEsalinkPartnerClient(UnitTestCase):
	def test_create_customer_returns_id_from_object(self):
		client = _partner()
		with patch.object(
			client, "_request", return_value=_FakeResponse({"customerId": 4242})
		) as req:
			cid = client.create_customer({"customerName": "ACME"})
		self.assertEqual(cid, 4242)
		self.assertEqual(req.call_args[0], ("POST", "/v1/customerPA"))
		self.assertEqual(req.call_args[1]["json"], {"customerName": "ACME"})

	def test_create_customer_returns_id_from_bare_value(self):
		client = _partner()
		with patch.object(
			client, "_request", return_value=_FakeResponse(payload=123, text="123")
		):
			self.assertEqual(client.create_customer({}), 123)

	def test_create_user_returns_credentials(self):
		client = _partner()
		creds = {"clientId": "u-1", "clientSecret": "s-1"}
		with patch.object(client, "_request", return_value=_FakeResponse(creds)) as req:
			out = client.create_user(99)
		self.assertEqual(out, creds)
		self.assertEqual(req.call_args[0], ("POST", "/v1/customerPA/99/user"))
		self.assertEqual(req.call_args[1]["json"], {"language": "fr_FR"})

	def test_create_identifier_body(self):
		client = _partner()
		with patch.object(client, "_request", return_value=_FakeResponse({})) as req:
			client.create_identifier(
				7, addressing_identifier="123456789", start_date="01-09-2026"
			)
		self.assertEqual(req.call_args[0], ("POST", "/v1/customerPA/7/identifier"))
		body = req.call_args[1]["json"]
		self.assertEqual(body["addressingIdentifier"], "123456789")
		self.assertEqual(body["addressingQualifier"], "0225")
		self.assertEqual(body["identifierType"], "RECEIVE")
		self.assertEqual(body["startDate"], "01-09-2026")

	def test_get_customer_and_resend_kyc_paths(self):
		client = _partner()
		with patch.object(
			client,
			"_request",
			return_value=_FakeResponse({"activationStatus": "ACTIVE"}),
		) as req:
			self.assertEqual(client.get_customer(5)["activationStatus"], "ACTIVE")
		self.assertEqual(req.call_args[0], ("GET", "/v1/customerPA/5"))
		with patch.object(client, "_request", return_value=_FakeResponse()) as req:
			client.resend_kyc_email(5)
		self.assertEqual(
			req.call_args[0], ("POST", "/v1/customerPA/5/resend-kyc-onboarding-email")
		)

	def test_search_customers_posts_to_search(self):
		client = _partner()
		with patch.object(
			client, "_request", return_value=_FakeResponse({"customers": [], "total": 0})
		) as req:
			out = client.search_customers(limit=50, offset=10)
		self.assertEqual(req.call_args[0], ("POST", "/v1/customerPA/search"))
		self.assertEqual(req.call_args[1]["params"], {"offset": 10, "limit": 50})
		self.assertEqual(out, {"customers": [], "total": 0})

	def test_find_customer_by_legal_id_matches_across_pages(self):
		client = _partner()
		pages = [
			_FakeResponse({"total": 3, "offset": 0, "limit": 2, "customers": [
				{"customerId": 1, "customerLegalId": "111111111"},
				{"customerId": 2, "customerLegalId": "222222222"},
			]}),
			_FakeResponse({"total": 3, "offset": 2, "limit": 2, "customers": [
				{"customerId": 3, "customerLegalId": "315143296"},
			]}),
		]
		with patch.object(client, "_request", side_effect=pages):
			self.assertEqual(client.find_customer_by_legal_id("315143296"), 3)

	def test_find_customer_by_legal_id_returns_none_when_absent(self):
		client = _partner()
		page = _FakeResponse({"total": 1, "offset": 0, "limit": 100, "customers": [
			{"customerId": 1, "customerLegalId": "111111111"},
		]})
		with patch.object(client, "_request", return_value=page):
			self.assertIsNone(client.find_customer_by_legal_id("999999999"))


class TestEsalinkProvisioningHelpers(UnitTestCase):
	def test_start_date_is_at_least_ten_days_ahead(self):
		import datetime

		from frappe.utils import getdate

		start = datetime.datetime.strptime(prov._start_date(), "%d-%m-%Y").date()
		self.assertGreaterEqual((start - getdate()).days, 10)

	def test_country_iso_maps_name_to_code(self):
		with patch("frappe.db.get_value", return_value="fr"):
			self.assertEqual(prov._country_iso("France"), "FR")
		self.assertEqual(prov._country_iso(None), "FR")

	def test_register_is_idempotent(self):
		existing = {
			"name": "Esalink — ACME",
			"esalink_customer_id": "42",
			"esalink_customer_status": "ACTIVE",
		}
		with (
			patch.object(prov, "_existing_esalink_platform", return_value=existing),
			patch.object(
				prov,
				"_partner_client",
				side_effect=AssertionError("must not register again"),
			),
		):
			out = prov.register_esalink_company("ACME")
		self.assertEqual(out["state"], "existing")
		self.assertEqual(out["customer_id"], "42")

	def test_register_reuses_existing_customer_by_siren(self):
		"""A company already present on Esalink (by SIREN) is reused, not re-created."""
		import etransactions.plateforme_agreee.session as session

		partner = MagicMock()
		partner.find_customer_by_legal_id.return_value = 55
		partner.create_user.return_value = {"clientId": "c-1", "clientSecret": "s-1"}
		fake_doc = MagicMock()
		fake_doc.name = "Esalink — ACME"
		fake_doc.get.return_value = None
		with (
			patch.object(prov, "_existing_esalink_platform", return_value=None),
			patch.object(prov, "_enhance_company"),
			patch.object(
				prov, "_build_customer_payload", return_value={"customerLegalId": "315143296"}
			),
			patch.object(prov, "_partner_client", return_value=partner),
			patch("frappe.new_doc", return_value=fake_doc),
			patch.object(
				session, "check_platform_health", return_value={"status": "ok", "message": "ok"}
			),
		):
			out = prov.register_esalink_company("ACME")
		partner.find_customer_by_legal_id.assert_called_once_with("315143296")
		partner.create_customer.assert_not_called()
		partner.create_user.assert_called_once_with(55)
		self.assertEqual(out["state"], "reused")
		self.assertEqual(out["customer_id"], "55")

	def test_register_creates_customer_when_absent(self):
		"""No Esalink customer for the SIREN → create_customer then create_user."""
		import etransactions.plateforme_agreee.session as session

		partner = MagicMock()
		partner.find_customer_by_legal_id.return_value = None
		partner.create_customer.return_value = 77
		partner.create_user.return_value = {"clientId": "c-2", "clientSecret": "s-2"}
		fake_doc = MagicMock()
		fake_doc.name = "Esalink — ACME"
		fake_doc.get.return_value = None
		with (
			patch.object(prov, "_existing_esalink_platform", return_value=None),
			patch.object(prov, "_enhance_company"),
			patch.object(
				prov, "_build_customer_payload", return_value={"customerLegalId": "315143296"}
			),
			patch.object(prov, "_partner_client", return_value=partner),
			patch("frappe.new_doc", return_value=fake_doc),
			patch.object(
				session, "check_platform_health", return_value={"status": "ok", "message": "ok"}
			),
		):
			out = prov.register_esalink_company("ACME")
		partner.create_customer.assert_called_once()
		partner.create_user.assert_called_once_with(77)
		self.assertEqual(out["state"], "created")
		self.assertEqual(out["customer_id"], "77")

	_BASE_CUSTOMER = {
		"customerName": "ACME",
		"customerLegalId": "315143296",
		"customerVat": "",
		"customerEmail": "a@b.fr",
		"addressLine1": "1 rue",
		"addressLine2": "",
		"postalCode": "75001",
		"city": "Paris",
		"country": "FR",
	}

	def test_payload_routing_address_defaults_to_siren(self):
		"""No routing address supplied → 0225:<SIREN> registered as the directory line."""
		with patch.object(prov, "_company_base_customer_data", return_value=dict(self._BASE_CUSTOMER)):
			payload = prov._build_customer_payload("ACME")
		self.assertEqual(
			payload["electronicAddresses"],
			[{"electronicAddress": "315143296", "qualifier": "0225"}],
		)
		self.assertEqual(payload["customerLegalId"], "315143296")
		# API user is minted explicitly via create_user(), not inline during customer creation.
		self.assertEqual(payload["apiUser"], "N")

	def test_payload_routing_address_override_parses_scheme(self):
		"""A scheme:value routing address is parsed; the legal id stays the SIREN."""
		with patch.object(prov, "_company_base_customer_data", return_value=dict(self._BASE_CUSTOMER)):
			payload = prov._build_customer_payload(
				"ACME", routing_address="0088:1234567890123"
			)
		self.assertEqual(
			payload["electronicAddresses"],
			[{"electronicAddress": "1234567890123", "qualifier": "0088"}],
		)
		self.assertEqual(payload["customerLegalId"], "315143296")

	def test_register_updates_named_platform_row(self):
		"""platform_name targets that exact (pre-created) row instead of creating a new one."""
		import etransactions.plateforme_agreee.session as session

		existing = {
			"name": "Esalink — ACME (Sales)",
			"esalink_customer_id": None,
			"esalink_customer_status": None,
			"is_active": 0,
		}
		partner = MagicMock()
		partner.find_customer_by_legal_id.return_value = None
		partner.create_customer.return_value = 99
		partner.create_user.return_value = {"clientId": "c-9", "clientSecret": "s-9"}
		fake_doc = MagicMock()
		fake_doc.name = "Esalink — ACME (Sales)"
		fake_doc.get.return_value = None
		with (
			patch.object(prov, "_target_esalink_platform", return_value=existing) as target,
			patch.object(prov, "_enhance_company"),
			patch.object(
				prov, "_build_customer_payload", return_value={"customerLegalId": "315143296"}
			),
			patch.object(prov, "_partner_client", return_value=partner),
			patch("frappe.get_doc", return_value=fake_doc) as get_doc,
			patch("frappe.new_doc", side_effect=AssertionError("must update the named row")),
			patch.object(
				session, "check_platform_health", return_value={"status": "ok", "message": "ok"}
			),
		):
			out = prov.register_esalink_company(
				"ACME", platform_name="Esalink — ACME (Sales)"
			)
		target.assert_called_once_with("ACME", "Esalink — ACME (Sales)")
		get_doc.assert_called_once_with(
			"eTransactions Accredited Platform", "Esalink — ACME (Sales)"
		)
		fake_doc.update.assert_called_once()
		self.assertEqual(out["platform_name"], "Esalink — ACME (Sales)")
		self.assertEqual(out["customer_id"], "99")

	def test_registration_status_not_registered(self):
		import frappe

		row = frappe._dict(
			{
				"company": "ACME",
				"esalink_customer_id": None,
				"esalink_customer_status": None,
				"is_active": 0,
				"esalink_environment": "test",
			}
		)

		def gv(doctype, *args, **kwargs):
			return "315143296" if doctype == "Company" else row

		with patch("frappe.db.get_value", side_effect=gv):
			out = prov.esalink_registration_status("P1")
		self.assertFalse(out["registered"])
		self.assertEqual(out["routing_address"], "0225:315143296")

	def test_registration_status_registered(self):
		import frappe

		row = frappe._dict(
			{
				"company": "ACME",
				"esalink_customer_id": "42",
				"esalink_customer_status": "ACTIVE",
				"is_active": 1,
				"esalink_environment": "prod",
			}
		)

		def gv(doctype, *args, **kwargs):
			return "315143296" if doctype == "Company" else row

		with patch("frappe.db.get_value", side_effect=gv):
			out = prov.esalink_registration_status("P1")
		self.assertTrue(out["registered"])
		self.assertEqual(out["customer_id"], "42")
		self.assertEqual(out["customer_status"], "ACTIVE")
		self.assertEqual(out["routing_address"], "0225:315143296")


class TestEsalinkIdentifierManagement(UnitTestCase):
	"""Partner-API identifier CRUD used for the company's own directory entries."""

	def test_search_identifiers_paginates(self):
		client = _partner()
		pages = [
			_FakeResponse({"total": 3, "offset": 0, "limit": 2, "identifiers": [
				{"identifier": "111", "qualifier": "0225", "identifierStatus": "DONE"},
				{"identifier": "222", "qualifier": "0225", "identifierStatus": "NEW"},
			]}),
			_FakeResponse({"total": 3, "offset": 2, "limit": 2, "identifiers": [
				{"identifier": "333", "qualifier": "0088", "identifierStatus": "IN_PROGRESS"},
			]}),
		]
		with patch.object(client, "_request", side_effect=pages) as req:
			rows = client.search_identifiers(42, limit=2)
		self.assertEqual([r["identifier"] for r in rows], ["111", "222", "333"])
		self.assertEqual(req.call_count, 2)
		args, kwargs = req.call_args_list[1]
		self.assertEqual(kwargs["params"], {"offset": 2, "limit": 2})

	def test_delete_identifier_uses_query_params(self):
		client = _partner()
		with patch.object(client, "_request", return_value=_FakeResponse()) as req:
			client.delete_identifier(42, "315143296", "0225")
		args, kwargs = req.call_args
		self.assertEqual(args[0], "DELETE")
		self.assertEqual(args[1], "/v1/customerPA/42/identifier")
		self.assertEqual(kwargs["params"], {"identifier": "315143296", "qualifier": "0225"})

	def test_update_identifier_body(self):
		client = _partner()
		with patch.object(client, "_request", return_value=_FakeResponse({})) as req:
			client.update_identifier(42, "315143296", "0225", start_date="20-07-2026")
		args, kwargs = req.call_args
		self.assertEqual(args[0], "PUT")
		self.assertEqual(kwargs["json"], {"startDate": "20-07-2026"})


class TestEsalinkDirectoryAdapter(UnitTestCase):
	"""The own-directory dialog adapter over the partner identifier API."""

	def _adapter(self):
		from etransactions.plateforme_agreee.own_directory import EsalinkDirectoryAdapter

		with patch(
			"etransactions.plateforme_agreee.esalink_provisioning._partner_client",
			return_value=MagicMock(),
		):
			return EsalinkDirectoryAdapter(42)

	def test_list_maps_to_dialog_shape(self):
		adapter = self._adapter()
		adapter.client.search_identifiers.return_value = [
			{"identifier": "315143296", "qualifier": "0225", "identifierStatus": "DONE"},
			{"identifier": "1234567890123", "qualifier": "0088", "identifierStatus": "NEW"},
		]
		entries = adapter.list_directory_entries()
		self.assertEqual(entries[0]["id"], "0225:315143296")
		self.assertEqual(entries[0]["directory"], "ppf")
		self.assertEqual(entries[0]["status"], "DONE")
		self.assertEqual(entries[1]["directory"], "peppol")

	def test_create_ppf_defaults_qualifier(self):
		adapter = self._adapter()
		adapter.client.create_identifier.return_value = {"identifierStatus": "NEW"}
		entry = adapter.create_directory_entry("315143296", "ppf")
		kwargs = adapter.client.create_identifier.call_args.kwargs
		self.assertEqual(kwargs["addressing_identifier"], "315143296")
		self.assertEqual(kwargs["addressing_qualifier"], "0225")
		self.assertTrue(kwargs["start_date"])
		self.assertEqual(entry["id"], "0225:315143296")

	def test_create_peppol_requires_scheme(self):
		import frappe

		adapter = self._adapter()
		with self.assertRaises(frappe.ValidationError):
			adapter.create_directory_entry("1234567890123", "peppol")
		adapter.client.create_identifier.return_value = {"identifierStatus": "NEW"}
		entry = adapter.create_directory_entry("0088:1234567890123", "peppol")
		self.assertEqual(entry["id"], "0088:1234567890123")

	def test_delete_splits_entry_id(self):
		adapter = self._adapter()
		adapter.delete_directory_entry("0225:315143296")
		adapter.client.delete_identifier.assert_called_once_with(42, "315143296", "0225")
