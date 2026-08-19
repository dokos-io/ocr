"""Esalink per-company operations client routed through the dokops proxy.

Subclasses :class:`AFNORClient` and overrides only the raw HTTP primitives
(``submit_flow``, ``get_flow_metadata``, ``download_flow_file``, ``search_flows``,
``get_siren``, ``search_directory_lines``, ``healthcheck``) -- every method built on top of
them (``submit_invoice``, ``get_invoice_status``, ``list_incoming_invoices``,
``download_flow``, ``get_directory_for_siren``, ``submit_lifecycle_status``,
``list_incoming_lifecycle_flows``, the CDAR/status-mapping logic, the b2c-unsupported
stubs) is inherited unchanged, so there is exactly one implementation of that business
logic regardless of whether calls go straight to Hubtimize or through dokops.

The company's own ``client_id``/``client_secret`` are forwarded on every call, never
persisted by dokops -- only the partner-level ``hubtimize-api-key`` moves off this site.
"""

import base64

from etransactions.components.afnor.client import AFNORClient
from etransactions.plateforme_agreee.dokos_connector import esalink_request

_METHOD_PREFIX = "dokops.esalink_proxy.operations_proxy"


class EsalinkProxyClient(AFNORClient):
	def __init__(self, client_id: str, client_secret: str, environment: str):
		# Deliberately does not call AFNORClient.__init__: that validates `requests`/`base_url`
		# for a client that talks to Hubtimize directly, neither of which applies here.
		self._client_id = client_id
		self._client_secret = client_secret
		self._environment = environment or "prod"

	def _call(self, method: str, **kwargs) -> dict:
		return esalink_request(
			f"{_METHOD_PREFIX}.{method}",
			client_id=self._client_id,
			client_secret=self._client_secret,
			environment=self._environment,
			**kwargs,
		)

	def healthcheck(self) -> None:
		self._call("healthcheck")

	def submit_flow(
		self,
		file_content: bytes,
		filename: str,
		syntax: str,
		tracking_id: str = None,
		processing_rule: str = None,
	) -> dict:
		return self._call(
			"submit_flow",
			file_content_b64=base64.b64encode(file_content).decode("ascii"),
			filename=filename,
			syntax=syntax,
			tracking_id=tracking_id,
			processing_rule=processing_rule,
		)

	def get_flow_metadata(self, flow_id: str) -> dict:
		return self._call("get_flow_metadata", flow_id=flow_id)

	def download_flow_file(self, flow_id: str) -> bytes:
		encoded = self._call("download_flow_file", flow_id=flow_id)
		return base64.b64decode(encoded)

	def search_flows(
		self,
		directions: list[str] = None,
		flow_types: list[str] = None,
		updated_after: str = None,
		updated_before: str = None,
		limit: int = 100,
	) -> list[dict]:
		return (
			self._call(
				"search_flows",
				directions=directions,
				flow_types=flow_types,
				updated_after=updated_after,
				updated_before=updated_before,
				limit=limit,
			)
			or []
		)

	def get_siren(self, siren: str) -> dict | None:
		return self._call("get_siren", siren=siren)

	def search_directory_lines(self, siren: str, limit: int = 100) -> list[dict]:
		return self._call("search_directory_lines", siren=siren, limit=limit) or []
