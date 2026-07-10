"""Esalink (HUBTIMIZE) clients — operations + partner provisioning.

Esalink is an AFNOR XP Z12-013 compliant Plateforme Agréée operated by HUBTIMIZE.
Its Flows/Directory APIs are the same shape as :class:`AFNORClient`, so the
operations client reuses that whole unified interface and only swaps the
transport: HUBTIMIZE authenticates with ``POST /v1/token`` (JSON
``{username, password}``) and requires a ``hubtimize-api-key`` header on every
call, rather than AFNOR's ``/v1/oauth2/token`` query-parameter grant.

Two clients share that transport:

* :class:`EsalinkClient` — per-company operations (send/receive invoices, lifecycle,
  directory). Credentials are the company's minted ``clientId`` / ``clientSecret``.
* :class:`EsalinkPartnerClient` — the integrator's Customer-management API
  (``/v1/customerPA``) used to create a customer account per company, mint its API
  credentials, register directory identifiers and poll the activation status.
  Credentials are the partner/integrator username/password.

Endpoints and payloads follow the official specs in ``components/ext/`` (Flows,
Directory, Customers).
"""

import time

import frappe
from frappe import _

from etransactions.components.afnor.client import AFNORClient
from etransactions.components.common import is_auth_error, throw_credentials_rejected

try:
    import requests
except ImportError:
    requests = None


# Base URLs per environment (no trailing slash, no /v1 — paths carry the /v1 prefix).
ESALINK_BASE_URLS = {
    "test": "https://ppd.hubtimize.fr/api/orchestrator",
    "prod": "https://hubtimize.fr/api/orchestrator",
}


def base_url_for_environment(environment: str) -> str:
    """Resolve the HUBTIMIZE base URL for ``test``/``prod`` (defaults to prod)."""
    return ESALINK_BASE_URLS.get(
        (environment or "prod").lower(), ESALINK_BASE_URLS["prod"]
    )


class _HubtimizeTransport:
    """Transport overrides shared by both Esalink clients.

    Reuses :class:`AFNORClient`'s request/flow/directory plumbing but replaces the
    auth: a JSON username/password token call plus the mandatory ``hubtimize-api-key``
    header. All Flows/Directory paths inherited from :class:`AFNORClient` already
    match HUBTIMIZE; only the token path differs.
    """

    _TOKEN_PATH = "/v1/token"
    _HEALTHCHECK_PATH = "/v1/healthcheck"

    def __init__(self, username: str, password: str, api_key: str, base_url: str):
        if not requests:
            frappe.throw(
                _("The 'requests' library is required for the Esalink client.")
            )
        if not base_url:
            frappe.throw(_("An Esalink base URL must be configured."))
        if not api_key:
            frappe.throw(
                _("The Esalink API key (hubtimize-api-key) must be configured.")
            )
        self._client_id = username
        self._client_secret = password
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def _fetch_token(self) -> None:
        """Acquire an access token via ``POST /v1/token`` (JSON username/password)."""
        resp = requests.post(
            f"{self._base_url}{self._TOKEN_PATH}",
            json={"username": self._client_id, "password": self._client_secret},
            headers={"hubtimize-api-key": self._api_key},
            timeout=30,
        )
        self._raise_for_status(resp)
        data = resp.json()
        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._token_expires_at = time.monotonic() + expires_in - 60

    def _headers(self, extra: dict | None = None) -> dict:
        h = {
            "Authorization": f"Bearer {self._token()}",
            "hubtimize-api-key": self._api_key,
        }
        if extra:
            h.update(extra)
        return h

    def healthcheck(self) -> None:
        """Probe connectivity with an authenticated ``GET /v1/healthcheck``."""
        self._request("GET", self._HEALTHCHECK_PATH)

    @staticmethod
    def _raise_for_status(resp: "requests.Response") -> None:
        if resp.ok:
            return
        try:
            body = resp.json()
            msg = (
                body.get("errorMessage")
                or body.get("message")
                or body.get("error")
                or resp.text[:300]
            )
        except Exception:
            msg = resp.text[:300]
        if is_auth_error(resp.status_code, msg):
            throw_credentials_rejected(msg)
        frappe.throw(
            _("Esalink API error {0}: {1}").format(resp.status_code, msg),
            frappe.ValidationError,
        )


class EsalinkClient(_HubtimizeTransport, AFNORClient):
    """Per-company operations client (send/receive flows, lifecycle, directory).

    Inherits the entire unified PA interface from :class:`AFNORClient`; the
    constructor and auth come from :class:`_HubtimizeTransport`.
    """


class EsalinkPartnerClient(_HubtimizeTransport, AFNORClient):
    """Integrator client for HUBTIMIZE's Customer-management API (``/v1/customerPA``).

    Authenticates with the partner credentials. Used to create a customer account
    per company, mint its API credentials, register directory identifiers and read
    the activation status. The inherited invoice methods are unused here.
    """

    _CUSTOMER_PATH = "/v1/customerPA"

    def create_customer(self, payload: dict) -> int:
        """``POST /v1/customerPA`` → the new customer's id.

        Triggers HUBTIMIZE's KYC/KYB onboarding email to ``customerEmail`` and, when
        ``electronicAddresses`` are supplied, registers the directory lines.
        """
        resp = self._request("POST", self._CUSTOMER_PATH, json=payload)
        return self._extract_customer_id(resp)

    def create_user(self, customer_id: int, language: str = "fr_FR") -> dict:
        """``POST /v1/customerPA/{id}/user`` → ``{clientId, clientSecret}``."""
        resp = self._request(
            "POST",
            f"{self._CUSTOMER_PATH}/{customer_id}/user",
            json={"language": language},
        )
        return resp.json()

    def list_users(self, customer_id: int) -> list[dict]:
        """``GET /v1/customerPA/{id}/user`` → list of users (clientId, enabled…)."""
        resp = self._request("GET", f"{self._CUSTOMER_PATH}/{customer_id}/user")
        return resp.json() or []

    def rotate_client_secret(self, customer_id: int, user_id: str) -> dict:
        """``POST /v1/customerPA/{id}/user/{userId}/clientSecret`` → new secret."""
        resp = self._request(
            "POST",
            f"{self._CUSTOMER_PATH}/{customer_id}/user/{user_id}/clientSecret",
        )
        return resp.json()

    def create_identifier(
        self,
        customer_id: int,
        *,
        addressing_identifier: str,
        start_date: str,
        addressing_qualifier: str = "0225",
        identifier_type: str = "RECEIVE",
        end_date: str = None,
        comment: str = None,
    ) -> dict:
        """``POST /v1/customerPA/{id}/identifier`` — request a directory identifier.

        ``identifier_type`` is ``SEND`` or ``RECEIVE``; ``start_date``/``end_date`` are
        ``DD-MM-YYYY`` (start must be ≥10 days in the future).
        """
        body = {
            "addressingIdentifier": addressing_identifier,
            "addressingQualifier": addressing_qualifier,
            "identifierType": identifier_type,
            "startDate": start_date,
        }
        if end_date:
            body["endDate"] = end_date
        if comment:
            body["comment"] = comment
        resp = self._request(
            "POST", f"{self._CUSTOMER_PATH}/{customer_id}/identifier", json=body
        )
        return resp.json() if resp.content else {}

    def search_identifiers(self, customer_id: int, limit: int = 100) -> list[dict]:
        """``POST /v1/customerPA/{id}/identifier/search`` — all identifiers, paginated."""
        identifiers: list[dict] = []
        offset = 0
        while True:
            resp = self._request(
                "POST",
                f"{self._CUSTOMER_PATH}/{customer_id}/identifier/search",
                params={"offset": offset, "limit": limit},
                json={},
            )
            data = resp.json() or {}
            page = data.get("identifiers") or []
            identifiers.extend(page)
            offset += len(page)
            if not page or offset >= (data.get("total") or 0):
                break
        return identifiers

    def get_identifier(self, customer_id: int, identifier: str, qualifier: str) -> dict:
        """``GET /v1/customerPA/{id}/identifier`` — one identifier by value+qualifier."""
        resp = self._request(
            "GET",
            f"{self._CUSTOMER_PATH}/{customer_id}/identifier",
            params={"identifier": identifier, "qualifier": qualifier},
        )
        return resp.json()

    def update_identifier(
        self,
        customer_id: int,
        identifier: str,
        qualifier: str,
        *,
        start_date: str = None,
        end_date: str = None,
    ) -> dict:
        """``PUT /v1/customerPA/{id}/identifier`` — reschedule an identifier.

        Dates are ``DD-MM-YYYY``; Esalink only allows updates for identifiers in
        status NEW/REFUSED/DONE (platform errors are surfaced as-is).
        """
        body = {}
        if start_date:
            body["startDate"] = start_date
        if end_date:
            body["endDate"] = end_date
        resp = self._request(
            "PUT",
            f"{self._CUSTOMER_PATH}/{customer_id}/identifier",
            params={"identifier": identifier, "qualifier": qualifier},
            json=body,
        )
        return resp.json() if resp.content else {}

    def delete_identifier(self, customer_id: int, identifier: str, qualifier: str) -> None:
        """``DELETE /v1/customerPA/{id}/identifier`` — remove an identifier.

        Only allowed for statuses NEW/REFUSED/DONE (platform errors surfaced as-is).
        """
        self._request(
            "DELETE",
            f"{self._CUSTOMER_PATH}/{customer_id}/identifier",
            params={"identifier": identifier, "qualifier": qualifier},
        )

    def get_customer(self, customer_id: int) -> dict:
        """``GET /v1/customerPA/{id}`` → customer detail incl. ``activationStatus``."""
        resp = self._request("GET", f"{self._CUSTOMER_PATH}/{customer_id}")
        return resp.json()

    def search_customers(self, limit: int = 100, offset: int = 0) -> dict:
        """``POST /v1/customerPA/search`` → one page ``{limit, offset, total, customers[]}``."""
        resp = self._request(
            "POST",
            f"{self._CUSTOMER_PATH}/search",
            params={"offset": offset, "limit": limit},
            json={},
        )
        return resp.json() or {}

    def find_customer_by_legal_id(self, legal_id: str) -> int | None:
        """Return the customer id whose ``customerLegalId`` matches ``legal_id``, else ``None``.

        The Customer API exposes no server-side filter, so page through the customer list
        and match locally (SIREN is unique, so the first match wins).
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
        """``POST /v1/customerPA/{id}/resend-kyc-onboarding-email`` — re-send onboarding."""
        self._request(
            "POST", f"{self._CUSTOMER_PATH}/{customer_id}/resend-kyc-onboarding-email"
        )

    @staticmethod
    def _extract_customer_id(resp: "requests.Response") -> int:
        """Parse the created customer id from a ``POST /v1/customerPA`` response.

        The spec is loose about the envelope (object ``{customerId}`` vs a bare id), so
        accept either.
        """
        try:
            data = resp.json()
        except Exception:
            data = (resp.text or "").strip()
        if isinstance(data, dict):
            cid = data.get("customerId") or data.get("id")
        else:
            cid = data
        if cid is None or (isinstance(cid, str) and not cid.isdigit()):
            frappe.throw(
                _("Esalink did not return a customer id: {0}").format(resp.text[:200])
            )
        return int(cid)
