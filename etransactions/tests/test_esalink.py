# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import MagicMock, patch

import frappe
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
		PROD = "https://hubtimize.fr/api/orchestrator"
		self.assertEqual(base_url_for_environment("prod"), PROD)
		self.assertEqual(base_url_for_environment("test"), BASE)
		self.assertEqual(base_url_for_environment(None), PROD)  # defaults to prod
		self.assertEqual(base_url_for_environment("nonsense"), PROD)

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

	def test_400_invalid_credentials_is_treated_as_an_auth_error(self):
		# HUBTIMIZE rejects a wrong-environment credential on /v1/token with a 400, not a
		# 401 — the operator must still get the "check the environment" guidance rather
		# than a raw "Esalink API error 400".
		resp = _FakeResponse(
			{
				"error": "Bad Request",
				"message": "Invalid credentials: Please check your username and password.",
			},
			status_code=400,
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			_ops_client()._raise_for_status(resp)
		self.assertIn("rejected the stored credentials", str(ctx.exception))

	def test_other_400s_still_surface_the_platform_message(self):
		resp = _FakeResponse(
			{"error": "Bad Request", "message": "startDate must be in the future"},
			status_code=400,
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			_ops_client()._raise_for_status(resp)
		message = str(ctx.exception)
		self.assertIn("startDate must be in the future", message)
		self.assertNotIn("rejected the stored credentials", message)


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

	def test_payload_bare_routing_address_takes_the_legal_id_type_scheme(self):
		"""The dialog sends a bare identifier: a SIRET must be filed under 0009, not 0225."""
		customer_data = dict(self._BASE_CUSTOMER, customerLegalId="31514329600011")
		with (
			patch.object(prov, "_company_base_customer_data", return_value=customer_data),
			patch.object(prov, "_legal_identifier", return_value=("31514329600011", "0009")),
		):
			payload = prov._build_customer_payload(
				"ACME", routing_address="31514329600011", legal_id_type="siret"
			)
		self.assertEqual(
			payload["electronicAddresses"],
			[{"electronicAddress": "31514329600011", "qualifier": "0009"}],
		)

	def test_normalize_legal_id_type_defaults_to_siren(self):
		self.assertEqual(prov._normalize_legal_id_type("SIRET"), "siret")
		self.assertEqual(prov._normalize_legal_id_type("siren"), "siren")
		self.assertEqual(prov._normalize_legal_id_type(None), "siren")
		self.assertEqual(prov._normalize_legal_id_type("vat"), "siren")  # unsupported → siren

	def test_payload_siret_routes_under_scheme_0009(self):
		"""SIRET legal id → customerLegalId is the SIRET and routing uses scheme 0009."""
		base = dict(self._BASE_CUSTOMER)
		base["customerLegalId"] = "31514329600011"
		with (
			patch.object(prov, "_company_base_customer_data", return_value=base),
			patch.object(prov, "_legal_identifier", return_value=("31514329600011", "0009")),
		):
			payload = prov._build_customer_payload("ACME", legal_id_type="siret")
		self.assertEqual(payload["customerLegalId"], "31514329600011")
		self.assertEqual(
			payload["electronicAddresses"],
			[{"electronicAddress": "31514329600011", "qualifier": "0009"}],
		)

	def test_enhance_company_skips_siren_writeback_for_siret(self):
		"""A SIRET must never be misfiled into Company.siren_number."""
		co = MagicMock()
		co.get.return_value = ""  # company lacks both SIREN and VAT
		with (
			patch("frappe.get_doc", return_value=co),
			patch("frappe.db.set_value") as set_value,
		):
			prov._enhance_company(
				"ACME", {"customerLegalId": "31514329600011", "customerVat": ""}, "siret"
			)
		set_value.assert_not_called()

	def test_enhance_company_writes_siren_for_siren_type(self):
		co = MagicMock()
		co.get.return_value = ""
		with (
			patch("frappe.get_doc", return_value=co),
			patch("frappe.db.set_value") as set_value,
		):
			prov._enhance_company("ACME", {"customerLegalId": "315143296"}, "siren")
		set_value.assert_called_once()
		self.assertEqual(set_value.call_args[0][2], {"siren_number": "315143296"})

	def test_register_persists_legal_id_type(self):
		"""The chosen legal-id type is written onto the platform row."""
		import etransactions.plateforme_agreee.session as session

		partner = MagicMock()
		partner.find_customer_by_legal_id.return_value = None
		partner.create_customer.return_value = 88
		partner.create_user.return_value = {"clientId": "c-8", "clientSecret": "s-8"}
		fake_doc = MagicMock()
		fake_doc.name = "Esalink — ACME"
		fake_doc.get.return_value = None
		with (
			patch.object(prov, "_existing_esalink_platform", return_value=None),
			patch.object(prov, "_enhance_company"),
			patch.object(
				prov, "_build_customer_payload", return_value={"customerLegalId": "31514329600011"}
			),
			patch.object(prov, "_partner_client", return_value=partner),
			patch("frappe.new_doc", return_value=fake_doc),
			patch.object(
				session, "check_platform_health", return_value={"status": "ok", "message": "ok"}
			),
		):
			prov.register_esalink_company("ACME", legal_id_type="siret")
		saved = fake_doc.update.call_args[0][0]
		self.assertEqual(saved["esalink_legal_id_type"], "siret")

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

	def _register_with_env(self, existing):
		"""Run a registration against ``existing`` and return (partner_client_mock, saved_dict)."""
		import etransactions.plateforme_agreee.session as session

		partner = MagicMock()
		partner.find_customer_by_legal_id.return_value = None
		partner.create_customer.return_value = 21
		partner.create_user.return_value = {"clientId": "c", "clientSecret": "s"}
		fake_doc = MagicMock()
		fake_doc.name = "Esalink — ACME"
		fake_doc.get.return_value = None
		with (
			patch.object(prov, "_existing_esalink_platform", return_value=existing),
			patch.object(prov, "_enhance_company"),
			patch.object(
				prov, "_build_customer_payload", return_value={"customerLegalId": "315143296"}
			),
			patch.object(prov, "_partner_client", return_value=partner) as pc,
			patch("frappe.get_doc", return_value=fake_doc),
			patch("frappe.new_doc", return_value=fake_doc),
			patch.object(
				session, "check_platform_health", return_value={"status": "ok", "message": "ok"}
			),
		):
			prov.register_esalink_company("ACME")
		return pc, fake_doc.update.call_args[0][0]

	def test_register_mints_on_the_row_environment(self):
		"""The row's environment picks the partner host and survives the save (no clobber)."""
		existing = {
			"name": "Esalink — ACME",
			"esalink_customer_id": None,
			"esalink_customer_status": None,
			"is_active": 0,
			"esalink_environment": "test",
		}
		pc, saved = self._register_with_env(existing)
		pc.assert_called_once_with("test")
		self.assertEqual(saved["esalink_environment"], "test")

	def test_register_defaults_new_row_to_prod(self):
		"""No pre-existing row → the account is minted on prod and the row records prod."""
		pc, saved = self._register_with_env(None)
		pc.assert_called_once_with("prod")
		self.assertEqual(saved["esalink_environment"], "prod")

	def test_refresh_customer_status_uses_row_environment(self):
		partner = MagicMock()
		partner.get_customer.return_value = {"activationStatus": "ACTIVE"}
		row = {"esalink_customer_id": "42", "esalink_environment": "test"}
		with (
			patch("frappe.db.get_value", side_effect=lambda dt, n, f, **k: row[f]),
			patch.object(prov, "_partner_client", return_value=partner) as pc,
			patch.object(prov, "_apply_customer_status"),
			patch("frappe.db.commit"),
		):
			out = prov.refresh_customer_status("P1")
		pc.assert_called_once_with("test")
		partner.get_customer.assert_called_once_with(42)
		self.assertEqual(out["status"], "ACTIVE")

	def test_resend_kyc_email_uses_row_environment(self):
		partner = MagicMock()
		row = {"esalink_customer_id": "42", "esalink_environment": "test"}
		with (
			patch("frappe.db.get_value", side_effect=lambda dt, n, f, **k: row[f]),
			patch.object(prov, "_partner_client", return_value=partner) as pc,
		):
			prov.resend_kyc_email("P1")
		pc.assert_called_once_with("test")
		partner.resend_kyc_email.assert_called_once_with(42)

	def test_platform_environment_defaults_to_prod(self):
		with patch("frappe.db.get_value", return_value=None):
			self.assertEqual(prov._platform_environment("P1"), "prod")

	def test_poll_builds_one_client_per_environment(self):
		"""Pending rows span both hosts, so the poll must not reuse a single partner client."""
		import frappe

		pending = [
			frappe._dict({"name": "P1", "esalink_customer_id": "1", "esalink_environment": "test"}),
			frappe._dict({"name": "P2", "esalink_customer_id": "2", "esalink_environment": "prod"}),
			frappe._dict({"name": "P3", "esalink_customer_id": "3", "esalink_environment": "test"}),
		]
		clients = {env: MagicMock(name=env) for env in ("test", "prod")}
		for c in clients.values():
			c.get_customer.return_value = {"activationStatus": "ACTIVE"}

		with (
			patch("frappe.get_all", return_value=pending),
			patch.object(prov, "_partner_client", side_effect=lambda env: clients[env]) as pc,
			patch.object(prov, "_apply_customer_status"),
			patch("frappe.db.commit"),
		):
			prov.poll_esalink_customer_statuses()

		# Two distinct environments across three rows → two clients, each cached and reused.
		self.assertEqual([c.args[0] for c in pc.call_args_list], ["test", "prod"])
		self.assertEqual(
			[c.args[0] for c in clients["test"].get_customer.call_args_list], [1, 3]
		)
		clients["prod"].get_customer.assert_called_once_with(2)

	def test_poll_fails_loudly_when_partner_credentials_missing(self):
		"""Clients are built before the per-row guard, so a config error is not swallowed."""
		import frappe

		pending = [
			frappe._dict({"name": "P1", "esalink_customer_id": "1", "esalink_environment": "prod"})
		]
		with (
			patch("frappe.get_all", return_value=pending),
			patch.object(prov, "_partner_client", side_effect=frappe.ValidationError("no creds")),
			patch.object(prov, "_apply_customer_status") as apply_status,
		):
			with self.assertRaises(frappe.ValidationError):
				prov.poll_esalink_customer_statuses()
		apply_status.assert_not_called()

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
		self.assertEqual(out["routing_address"], "315143296")

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
		self.assertEqual(out["legal_id_type"], "siren")
		self.assertEqual(out["routing_address"], "315143296")

	def test_registration_status_uses_persisted_siret(self):
		import frappe

		row = frappe._dict(
			{
				"company": "ACME",
				"esalink_customer_id": "42",
				"esalink_customer_status": "ACTIVE",
				"is_active": 1,
				"esalink_environment": "test",
				"esalink_legal_id_type": "siret",
			}
		)

		def gv(doctype, *args, **kwargs):
			return "315143296" if doctype == "Company" else row

		with (
			patch("frappe.db.get_value", side_effect=gv),
			patch.object(prov, "_legal_identifier", return_value=("31514329600011", "0009")),
		):
			out = prov.esalink_registration_status("P1")
		self.assertEqual(out["legal_id_type"], "siret")
		self.assertEqual(out["routing_address"], "31514329600011")


class TestEsalinkPartnerGate(UnitTestCase):
	"""Cloud-aware hard block when the Esalink partner credentials are missing."""

	def test_is_dokos_cloud_flag_and_hostname_fallback(self):
		import frappe

		had = "dokos_cloud" in frappe.conf
		prev = frappe.conf.get("dokos_cloud")
		try:
			# Explicit flag wins even when no host looks like a cloud host.
			frappe.conf["dokos_cloud"] = 1
			with patch.object(prov, "_dokos_cloud_candidate_hosts", return_value=[]):
				self.assertTrue(prov.is_dokos_cloud())
			# No flag → the .dokos.cloud host suffix decides.
			frappe.conf["dokos_cloud"] = 0
			with patch.object(prov, "_dokos_cloud_candidate_hosts", return_value=["acme.dokos.cloud"]):
				self.assertTrue(prov.is_dokos_cloud())
			with patch.object(prov, "_dokos_cloud_candidate_hosts", return_value=["acme.example.com"]):
				self.assertFalse(prov.is_dokos_cloud())
		finally:
			if had:
				frappe.conf["dokos_cloud"] = prev
			else:
				frappe.conf.pop("dokos_cloud", None)

	def test_host_is_dokos_cloud_strips_scheme_and_port(self):
		self.assertTrue(prov._host_is_dokos_cloud("https://acme.dokos.cloud:443/app"))
		self.assertFalse(prov._host_is_dokos_cloud("acme.dokos.io"))

	def test_message_points_to_dokos_support_on_cloud(self):
		with patch.object(prov, "is_dokos_cloud", return_value=True):
			self.assertIn("help@dokos.cloud", prov._partner_credentials_message())

	def test_message_points_to_account_manager_when_self_hosted(self):
		with patch.object(prov, "is_dokos_cloud", return_value=False):
			msg = prov._partner_credentials_message()
		self.assertIn("account manager at Esalink", msg)
		self.assertNotIn("help@dokos.cloud", msg)

	def test_partner_status_blocks_when_unconfigured(self):
		with (
			patch.object(prov, "partner_credentials_configured", return_value=False),
			patch.object(prov, "is_dokos_cloud", return_value=False),
		):
			out = prov.esalink_partner_status()
		self.assertFalse(out["configured"])
		self.assertFalse(out["is_cloud"])
		self.assertIn("account manager at Esalink", out["message"])

	def test_partner_status_ok_when_configured(self):
		with patch.object(prov, "partner_credentials_configured", return_value=True):
			out = prov.esalink_partner_status()
		self.assertTrue(out["configured"])
		self.assertIsNone(out["message"])

	def test_new_esalink_platform_validate_blocks_without_partner_config(self):
		import frappe

		doc = frappe.new_doc("eTransactions Accredited Platform")
		doc.platform_type = "Esalink"
		with patch.object(prov, "partner_credentials_configured", return_value=False):
			with self.assertRaises(frappe.ValidationError):
				doc.validate()

	def test_new_esalink_platform_validate_passes_when_configured(self):
		import frappe

		doc = frappe.new_doc("eTransactions Accredited Platform")
		doc.platform_type = "Esalink"
		with patch.object(prov, "partner_credentials_configured", return_value=True):
			doc.validate()  # Esalink is exempt from record-level client credentials


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

	def test_adapter_builds_partner_client_for_the_row_environment(self):
		from etransactions.plateforme_agreee.own_directory import EsalinkDirectoryAdapter

		with patch(
			"etransactions.plateforme_agreee.esalink_provisioning._partner_client",
			return_value=MagicMock(),
		) as pc:
			EsalinkDirectoryAdapter(42, "test")
		pc.assert_called_once_with("test")

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
