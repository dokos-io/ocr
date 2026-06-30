# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from etransactions.components.superpdp.client import SuperPDPClient
from etransactions.components.superpdp.models import B2CTransaction, B2CTransactionSubtotal


class _FakeResponse:
	"""Minimal stand-in for requests.Response used to drive the client offline."""

	def __init__(self, payload=None, content=b""):
		self._payload = payload or {}
		self.content = content
		self.ok = True
		self.status_code = 200

	def json(self):
		return self._payload


def _client() -> SuperPDPClient:
	c = SuperPDPClient("client-id", "client-secret")
	# Pretend we already hold a valid token so no method tries to authenticate.
	c._access_token = "tok"
	c._token_expires_at = float("inf")
	return c


class TestSuperPDPEreporting(UnitTestCase):
	"""SuperPDP e-reporting client methods, exercised with a mocked transport."""

	def test_create_b2c_transactions_payload(self):
		client = _client()
		txn = B2CTransaction(
			date="2026-06-05",
			currency="EUR",
			category_code="TLB1",
			tax_exclusive_amount="100",
			tax_total="20",
			role_code="SE",
			tax_subtotals=[B2CTransactionSubtotal("20", "100", "20")],
		)
		with patch.object(client, "_request", return_value=_FakeResponse({"data": [{"id": 42}]})) as req:
			created = client.create_b2c_transactions([txn])

		self.assertEqual(created, [{"id": 42}])
		args, kwargs = req.call_args
		self.assertEqual(args[0], "POST")
		self.assertEqual(args[1], "/v1.beta/b2c_transactions")
		body = kwargs["json"]
		self.assertEqual(len(body["data"]), 1)
		self.assertNotIn("id", body["data"][0])
		self.assertEqual(body["data"][0]["category_code"], "TLB1")

	def test_update_vat_regime(self):
		client = _client()
		with patch.object(client, "_request", return_value=_FakeResponse({"vat_regime": "monthly"})) as req:
			client.update_vat_regime("monthly")
		args, kwargs = req.call_args
		self.assertEqual(args[0], "PATCH")
		self.assertEqual(args[1], "/v1.beta/companies")
		self.assertEqual(kwargs["json"], {"vat_regime": "monthly"})

	def test_paginate_follows_has_after(self):
		client = _client()
		pages = [
			_FakeResponse({"data": [{"id": 1}, {"id": 2}], "has_after": True}),
			_FakeResponse({"data": [{"id": 3}], "has_after": False}),
		]
		with patch.object(client, "_request", side_effect=pages):
			items = client._paginate("/v1.beta/b2c_transactions")
		self.assertEqual([i["id"] for i in items], [1, 2, 3])

	def test_list_ereportings_maps_to_dataclass(self):
		client = _client()
		raw = {
			"data": [
				{
					"id": 7,
					"kind": "transaction",
					"role_code": "SE",
					"start_period": "2026-06-01",
					"end_period": "2026-06-10",
					"events": [
						{"status_code": "ppf:ereporting", "created_at": "2026-06-11T00:00:00Z"},
						{"status_code": "ppf:ereporting-response-ok", "created_at": "2026-06-12T00:00:00Z"},
					],
				}
			],
			"has_after": False,
		}
		with patch.object(client, "_request", return_value=_FakeResponse(raw)):
			results = client.list_ereportings()

		self.assertEqual(len(results), 1)
		decl = results[0]
		self.assertEqual(decl.id, "7")
		self.assertEqual(decl.kind, "transaction")
		self.assertEqual(len(decl.events), 2)
		self.assertEqual(decl.events[1].status_code, "ppf:ereporting-response-ok")

	def test_list_invoice_events_paginates(self):
		client = _client()
		pages = [
			_FakeResponse({"data": [{"id": 1, "status_code": "fr:204"}], "has_after": True}),
			_FakeResponse({"data": [{"id": 2, "status_code": "fr:205"}], "has_after": False}),
		]
		with patch.object(client, "_request", side_effect=pages):
			events = client.list_invoice_events(invoice_id=99)
		self.assertEqual([e["id"] for e in events], [1, 2])


def _error_response(payload, status_code=400):
	resp = _FakeResponse(payload)
	resp.ok = False
	resp.status_code = status_code
	resp.text = str(payload)
	return resp


class TestSuperPDPRaiseForStatus(UnitTestCase):
	"""_raise_for_status maps known platform errors to actionable messages."""

	def test_receiver_not_in_directory_is_actionable(self):
		resp = _error_response(
			{"message": "pre-check: receiver address does not exist in peppol directory"}
		)
		with self.assertRaises(frappe.ValidationError) as cm:
			SuperPDPClient._raise_for_status(resp)
		message = str(cm.exception)
		# The actionable branch fired, not the raw "SuperPDP API error" fallback.
		self.assertIn("routing address could not be found", message)
		self.assertNotIn("SuperPDP API error", message)

	def test_missing_seller_identifier_branch_unaffected(self):
		resp = _error_response({"message": "Seller.LegalRegistrationIdentifier is required"})
		with self.assertRaises(frappe.ValidationError) as cm:
			SuperPDPClient._raise_for_status(resp)
		self.assertIn("legal registration identifier", str(cm.exception))

	def test_unrelated_error_falls_back_to_generic(self):
		resp = _error_response({"message": "some other failure"}, status_code=500)
		with self.assertRaises(frappe.ValidationError) as cm:
			SuperPDPClient._raise_for_status(resp)
		self.assertIn("SuperPDP API error 500", str(cm.exception))


class TestSuperPDPOwnDirectory(UnitTestCase):
	"""Own-company directory entry methods route to the right endpoints."""

	def test_create_directory_entry_payload(self):
		client = _client()
		with patch.object(client, "_request", return_value=_FakeResponse({"id": 5, "identifier": "0225:123", "directory": "ppf"})) as req:
			created = client.create_directory_entry("0225:123", "ppf")
		args, kwargs = req.call_args
		self.assertEqual(args[0], "POST")
		self.assertEqual(args[1], "/v1.beta/directory_entries")
		self.assertEqual(kwargs["json"], {"identifier": "0225:123", "directory": "ppf"})
		self.assertEqual(created["directory"], "ppf")

	def test_list_directory_entries(self):
		client = _client()
		with patch.object(client, "_request", return_value=_FakeResponse({"data": [{"id": 1}]})) as req:
			entries = client.list_directory_entries()
		self.assertEqual(req.call_args.args, ("GET", "/v1.beta/directory_entries"))
		self.assertEqual(entries, [{"id": 1}])

	def test_delete_directory_entry(self):
		client = _client()
		with patch.object(client, "_request", return_value=_FakeResponse()) as req:
			client.delete_directory_entry(9)
		self.assertEqual(req.call_args.args, ("DELETE", "/v1.beta/directory_entries/9"))

	def test_register_rejects_invalid_directory(self):
		from etransactions.plateforme_agreee import own_directory

		with self.assertRaises(Exception):
			own_directory.register_directory_entry("Platform", "0225:123", "bogus")


class TestUnsupportedPlatforms(UnitTestCase):
	"""AFNOR/Esalink clients reject e-reporting as a backstop to capability gating."""

	def test_afnor_raises(self):
		from etransactions.components.afnor.client import AFNORClient

		client = AFNORClient.__new__(AFNORClient)  # skip __init__/auth
		with self.assertRaises(Exception):
			client.create_b2c_transactions([])

	def test_esalink_raises(self):
		from etransactions.components.esalink import EsalinkClient

		client = EsalinkClient.__new__(EsalinkClient)  # skip __init__/auth
		with self.assertRaises(Exception):
			client.update_vat_regime("monthly")


class TestOAuthOnboardingHelpers(UnitTestCase):
	"""Pure-logic checks for the authorization_code + PKCE onboarding helpers."""

	def test_pkce_pair_is_url_safe_and_distinct(self):
		import base64
		import hashlib

		verifier, challenge = SuperPDPClient.generate_pkce_pair()
		self.assertNotEqual(verifier, challenge)
		# challenge == base64url(sha256(verifier)) without padding
		expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
		self.assertEqual(challenge, expected)

	def test_authorize_url_carries_pkce_and_company(self):
		from urllib.parse import parse_qs, urlparse

		url = SuperPDPClient.build_authorize_url(
			client_id="cid",
			redirect_uri="https://erp.example/cb",
			state="st",
			code_challenge="ch",
			base_url="https://api.superpdp.tech",
			company_number="853322915",
			company_number_scheme="fr_siren",
		)
		q = parse_qs(urlparse(url).query)
		self.assertEqual(q["response_type"], ["code"])
		self.assertEqual(q["code_challenge_method"], ["S256"])
		self.assertEqual(q["code_challenge"], ["ch"])
		self.assertEqual(q["state"], ["st"])
		self.assertEqual(q["superpdp_company_number"], ["853322915"])
		self.assertEqual(q["superpdp_company_number_scheme"], ["fr_siren"])

	def test_authorization_code_client_refreshes_token(self):
		captured = {}

		def fake_post(url, data=None, timeout=None):
			captured.update(data or {})
			return _FakeResponse({"access_token": "new-tok", "expires_in": 3600, "refresh_token": "r2"})

		persisted = {}
		client = SuperPDPClient(
			"cid",
			"",
			auth_method="authorization_code",
			refresh_token="r1",
			on_token_refreshed=lambda d: persisted.update(d),
		)
		with patch("etransactions.components.superpdp.client.requests.post", side_effect=fake_post):
			self.assertEqual(client._token(), "new-tok")
		self.assertEqual(captured["grant_type"], "refresh_token")
		self.assertEqual(captured["refresh_token"], "r1")
		# rotated refresh token is adopted and persisted
		self.assertEqual(client._refresh_token, "r2")
		self.assertEqual(persisted["refresh_token"], "r2")
