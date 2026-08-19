# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

import base64
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from etransactions.components.esalink import EsalinkPartnerProxyClient, EsalinkProxyClient
from etransactions.plateforme_agreee import dokos_connector, esalink_provisioning as prov
from etransactions.plateforme_agreee import session


class TestEsalinkProxyClientForwarding(UnitTestCase):
	def test_submit_flow_forwards_base64_and_credentials(self):
		client = EsalinkProxyClient(client_id="cid", client_secret="secret", environment="test")
		with patch(
			"etransactions.components.esalink.proxy_client.esalink_request", return_value={"flowId": "F1"}
		) as req:
			result = client.submit_flow(b"<xml/>", "invoice.xml", "UBL", tracking_id="T1")

		self.assertEqual(result["flowId"], "F1")
		args, kwargs = req.call_args
		self.assertEqual(args[0], "dokops.esalink_proxy.operations_proxy.submit_flow")
		self.assertEqual(kwargs["client_id"], "cid")
		self.assertEqual(kwargs["client_secret"], "secret")
		self.assertEqual(kwargs["environment"], "test")
		self.assertEqual(base64.b64decode(kwargs["file_content_b64"]), b"<xml/>")
		self.assertEqual(kwargs["tracking_id"], "T1")

	def test_download_flow_file_decodes_base64(self):
		client = EsalinkProxyClient(client_id="cid", client_secret="secret", environment="prod")
		encoded = base64.b64encode(b"file-bytes").decode()
		with patch("etransactions.components.esalink.proxy_client.esalink_request", return_value=encoded):
			content = client.download_flow_file("F1")
		self.assertEqual(content, b"file-bytes")

	def test_get_siren_passthrough_of_none(self):
		client = EsalinkProxyClient(client_id="cid", client_secret="secret", environment="prod")
		with patch(
			"etransactions.components.esalink.proxy_client.esalink_request", return_value=None
		) as req:
			result = client.get_siren("315143296")
		self.assertIsNone(result)
		self.assertEqual(req.call_args.kwargs["siren"], "315143296")

	def test_never_forwards_a_partner_api_key(self):
		"""The proxy client's whole point: no partner secret exists here to leak."""
		client = EsalinkProxyClient(client_id="cid", client_secret="secret", environment="test")
		self.assertFalse(hasattr(client, "_api_key"))

	def test_inherits_unified_interface_from_afnor_client(self):
		"""submit_invoice etc. are inherited unchanged -- only the raw primitives differ."""
		client = EsalinkProxyClient(client_id="cid", client_secret="secret", environment="test")
		with patch.object(
			client,
			"submit_flow",
			return_value={"flowId": "F9", "submittedAt": "2026-01-01T00:00:00Z", "flowSyntax": "UBL"},
		):
			result = client.submit_invoice(b"<xml/>", "invoice.xml", "UBL", external_id="X1")
		self.assertEqual(result.flow_id, "F9")
		self.assertEqual(result.flow_type, "CustomerInvoice")


class TestEsalinkPartnerProxyClientForwarding(UnitTestCase):
	def test_create_customer_forwards_environment_and_payload(self):
		client = EsalinkPartnerProxyClient(environment="test")
		with patch(
			"etransactions.components.esalink.partner_proxy_client.esalink_request", return_value=42
		) as req:
			cid = client.create_customer({"customerName": "Acme"})
		self.assertEqual(cid, 42)
		args, kwargs = req.call_args
		self.assertEqual(args[0], "dokops.esalink_proxy.partner_proxy.create_customer")
		self.assertEqual(kwargs["environment"], "test")
		self.assertEqual(kwargs["payload"], {"customerName": "Acme"})

	def test_find_customer_by_legal_id_paginates(self):
		client = EsalinkPartnerProxyClient(environment="prod")
		pages = [
			{
				"total": 3,
				"customers": [
					{"customerId": 1, "customerLegalId": "111"},
					{"customerId": 2, "customerLegalId": "222"},
				],
			},
			{"total": 3, "customers": [{"customerId": 3, "customerLegalId": "333"}]},
		]
		with patch.object(client, "search_customers", side_effect=pages):
			self.assertEqual(client.find_customer_by_legal_id("333"), 3)

	def test_never_holds_partner_credentials(self):
		client = EsalinkPartnerProxyClient(environment="test")
		self.assertFalse(hasattr(client, "_password"))
		self.assertFalse(hasattr(client, "_username"))


class TestEsalinkProxyModeSwitching(UnitTestCase):
	"""No separate opt-in flag: whether the shared dokos_connector_* triplet is configured
	*is* the toggle, exactly like Bridge's own bank_api -> bridge_proxy cutover."""

	def test_use_proxy_requires_all_three_connector_keys(self):
		keys = ("dokos_connector_url", "dokos_connector_client_id", "dokos_connector_client_secret")
		saved = {k: frappe.conf.get(k) for k in keys}
		try:
			frappe.conf["dokos_connector_url"] = "https://x"
			frappe.conf["dokos_connector_client_id"] = "id"
			frappe.conf["dokos_connector_client_secret"] = None
			self.assertFalse(dokos_connector.use_proxy())

			frappe.conf["dokos_connector_client_secret"] = "secret"
			self.assertTrue(dokos_connector.use_proxy())
		finally:
			for k, v in saved.items():
				if v is None:
					frappe.conf.pop(k, None)
				else:
					frappe.conf[k] = v

	def test_partner_client_returns_proxy_client_when_connector_configured(self):
		with patch.object(prov, "use_proxy", return_value=True):
			client = prov._partner_client("test")
		self.assertIsInstance(client, EsalinkPartnerProxyClient)

	def test_partner_client_raises_when_nothing_is_configured(self):
		with (
			patch.object(prov, "use_proxy", return_value=False),
			patch.object(prov, "esalink_partner_config", return_value={"username": "", "password": "", "api_key": "", "base_url": ""}),
		):
			with self.assertRaises(frappe.ValidationError):
				prov._partner_client("test")

	def test_partner_credentials_configured_checks_connector_first(self):
		with patch.object(prov, "use_proxy", return_value=True):
			self.assertTrue(prov.partner_credentials_configured())

	def test_build_client_uses_proxy_client_when_enabled(self):
		with patch("etransactions.plateforme_agreee.dokos_connector.use_proxy", return_value=True):
			client = session._build_client("Esalink", "cid", "secret", esalink_environment="test")
		self.assertIsInstance(client, EsalinkProxyClient)

	def test_build_client_uses_direct_client_when_disabled(self):
		from etransactions.components.esalink import EsalinkClient

		with (
			patch("etransactions.plateforme_agreee.dokos_connector.use_proxy", return_value=False),
			patch.object(prov, "esalink_api_key", return_value="key-123"),
		):
			client = session._build_client("Esalink", "cid", "secret", esalink_environment="test")
		self.assertIsInstance(client, EsalinkClient)
