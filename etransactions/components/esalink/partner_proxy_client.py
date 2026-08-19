"""Esalink partner (Customer-management) client routed through the dokops proxy.

Implements the same method surface as :class:`EsalinkPartnerClient`
(``etransactions.components.esalink.client``) that :mod:`esalink_provisioning` actually
calls, so its business logic (payload building, Company/Address mapping, eTransactions
Accredited Platform bookkeeping) needs no changes beyond swapping which client
``_partner_client()`` builds. The partner credentials never reach this site: dokops holds
them, and this client only forwards ``environment`` plus the call's own arguments.
"""

from etransactions.plateforme_agreee.dokos_connector import esalink_request

_METHOD_PREFIX = "dokops.esalink_proxy.partner_proxy"


class EsalinkPartnerProxyClient:
	def __init__(self, environment: str):
		self._environment = environment or "prod"

	def create_customer(self, payload: dict) -> int:
		"""``POST /v1/customerPA`` -> the new customer's id (proxied)."""
		return esalink_request(
			f"{_METHOD_PREFIX}.create_customer", environment=self._environment, payload=payload
		)

	def create_user(self, customer_id: int, language: str = "fr_FR") -> dict:
		"""``POST /v1/customerPA/{id}/user`` -> ``{clientId, clientSecret}`` (proxied)."""
		return esalink_request(
			f"{_METHOD_PREFIX}.create_user",
			environment=self._environment,
			customer_id=customer_id,
			language=language,
		)

	def get_customer(self, customer_id: int) -> dict:
		"""``GET /v1/customerPA/{id}`` -> customer detail incl. ``activationStatus`` (proxied)."""
		return esalink_request(
			f"{_METHOD_PREFIX}.get_customer", environment=self._environment, customer_id=customer_id
		)

	def search_customers(self, limit: int = 100, offset: int = 0) -> dict:
		"""``POST /v1/customerPA/search`` -> one page (proxied)."""
		return (
			esalink_request(
				f"{_METHOD_PREFIX}.search_customers",
				environment=self._environment,
				limit=limit,
				offset=offset,
			)
			or {}
		)

	def find_customer_by_legal_id(self, legal_id: str) -> int | None:
		"""Return the customer id whose ``customerLegalId`` matches ``legal_id``, else ``None``.

		Same client-side pagination as :class:`EsalinkPartnerClient`: the Customer API exposes
		no server-side filter, so page through the customer list and match locally.
		"""
		target = str(legal_id).strip()
		if not target:
			return None
		limit, offset = 100, 0
		while True:
			page = self.search_customers(limit=limit, offset=offset)
			customers = page.get("customers") or []
			for cust in customers:
				if str(cust.get("customerLegalId") or "").strip() == target:
					cid = cust.get("customerId") or cust.get("id")
					return int(cid) if cid is not None else None
			offset += len(customers)
			if not customers or offset >= (page.get("total") or 0):
				return None

	def resend_kyc_email(self, customer_id: int) -> None:
		"""``POST /v1/customerPA/{id}/resend-kyc-onboarding-email`` (proxied)."""
		esalink_request(
			f"{_METHOD_PREFIX}.resend_kyc_email", environment=self._environment, customer_id=customer_id
		)

	def healthcheck(self) -> None:
		"""Probe partner connectivity via a cheap, side-effect-free search call."""
		self.search_customers(limit=1, offset=0)
