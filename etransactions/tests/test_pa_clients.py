# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import patch

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


class TestUnsupportedPlatforms(UnitTestCase):
	"""AFNOR/Esalink clients reject e-reporting as a backstop to capability gating."""

	def test_afnor_raises(self):
		from etransactions.components.afnor.client import AFNORClient

		client = AFNORClient.__new__(AFNORClient)  # skip __init__/auth
		with self.assertRaises(Exception):
			client.create_b2c_transactions([])

	def test_esalink_raises(self):
		from etransactions.plateforme_agreee.esalink import ESALINKClient

		client = ESALINKClient.__new__(ESALINKClient)
		with self.assertRaises(Exception):
			client.update_vat_regime("monthly")
