# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt
"""OAuth2 client-credentials connection to the dokops Esalink proxy.

Mirrors ``bank.bank.__init__``'s connector to the Bridge proxy -- same shape, same
``dokos_connector_*`` site_config keys (shared with every other proxied service, since a
site is provisioned with one identity for all of them; see
``dokops.dokops_accounts.provisioning.provision_account``).
"""

import frappe
import requests
from frappe import _
from frappe.frappeclient import FrappeException, FrappeOAuth2Client

TOKEN_CACHE_KEY = "esalink_connector_access_token"


def _get_access_token():
	"""Obtain (and cache) an OAuth2 client_credentials access token for the proxy."""
	token = frappe.cache().get_value(TOKEN_CACHE_KEY)
	if token:
		return token

	token_uri = frappe.conf.get("dokos_connector_token_uri")
	if not token_uri:
		frappe.throw(_("dokos_connector_token_uri is not configured"))

	response = requests.post(
		token_uri,
		data={
			"grant_type": "client_credentials",
			"client_id": frappe.conf.get("dokos_connector_client_id"),
			"client_secret": frappe.conf.get("dokos_connector_client_secret"),
		},
		timeout=30,
	)
	data = response.json()
	token = data.get("access_token")
	if not token:
		frappe.throw(_("Could not obtain dokos connector access token: {0}").format(data))

	expires_in = int(data.get("expires_in") or 3600)
	frappe.cache().set_value(TOKEN_CACHE_KEY, token, expires_in_sec=max(60, expires_in - 60))
	return token


class DokosClient(FrappeOAuth2Client):
	def post_process(self, response):
		try:
			return super().post_process(response)
		except FrappeException as e:
			if "frappe.exceptions.AuthenticationError" in str(e):
				# Token may have been revoked/expired server-side; drop the cache.
				frappe.cache().delete_value(TOKEN_CACHE_KEY)
				frappe.throw(_("Authentication error: Please check your Esalink connector credentials."))
			raise


def dokos_client_connection(url=None):
	base = frappe.conf.get("dokos_connector_url")
	if not base:
		frappe.throw(_("dokos_connector_url is not configured"))
	return DokosClient(url=f"{base}{url}", access_token=_get_access_token())


def esalink_request(endpoint: str, **kwargs):
	"""Call a named dokops Esalink proxy RPC (``/api/method/<endpoint>``)."""
	connection = dokos_client_connection(f"/api/method/{endpoint}")
	return connection.post_request(kwargs)


def use_proxy() -> bool:
	"""Whether this site routes Esalink calls through dokops instead of Hubtimize directly.

	No separate opt-in flag: Bridge's own bank_api -> bridge_proxy cutover never used one
	either -- which backend a site reaches is decided purely by whether its connector
	credentials (here, the shared ``dokos_connector_*`` triplet) are configured, mirroring
	``bank_connector_url`` for Bridge. A Dokos Cloud site gets these auto-provisioned (see
	``dokops.www.cnuage.v1.create_update_site``); an external self-hosted site is cut over
	by running ``dokops.dokops_accounts.provisioning.provision_account`` and writing the
	result into its site_config -- in both cases, configuring the connector *is* opting in,
	so there's nothing else to flip.
	"""
	return bool(
		frappe.conf.get("dokos_connector_url")
		and frappe.conf.get("dokos_connector_client_id")
		and frappe.conf.get("dokos_connector_client_secret")
	)
