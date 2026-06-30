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

	def test_resolve_company_list_parses_inputs(self):
		self.assertEqual(prov._resolve_company_list('["A","B"]'), ["A", "B"])
		self.assertEqual(prov._resolve_company_list("A, B"), ["A", "B"])

	def test_provision_company_is_idempotent(self):
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
				side_effect=AssertionError("must not provision again"),
			),
		):
			out = prov.provision_company("ACME")
		self.assertEqual(out["state"], "existing")
		self.assertEqual(out["customer_id"], "42")
