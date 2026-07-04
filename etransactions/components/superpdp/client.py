"""SuperPDP API client.

Implements the unified platform client interface (send_invoice, get_invoice_status,
list_incoming_invoices, download_invoice, get_directory_for_siren) required by
etransactions.plateforme_agreee, plus direct access to all SuperPDP API endpoints.

API reference: https://api.superpdp.tech (OpenAPI spec: components/ext/superpdp.json)
"""

import time
from dataclasses import asdict, is_dataclass
from datetime import datetime

import frappe
from frappe import _

from etransactions.components.common import to_db_datetime as _to_db_datetime
from etransactions.components.superpdp.models import (
    B2CPayment,
    B2CTransaction,
    DirectoryData,
    DirectoryLineData,
    EreportingEvent,
    EreportingResult,
    FlowResult,
    IncomingFlow,
    LifecycleEvent,
    LifecycleResult,
    StatusResult,
)
from etransactions.plateforme_agreee import lifecycle_status

try:
    import requests
except ImportError:
    requests = None


def _months_between(start: datetime, end: datetime) -> list[str]:
    """Month strings (``YYYY-MM``) covering [start, end], oldest first."""
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def _ereporting_payload(obj) -> dict:
    """Serialize a B2C transaction/payment dataclass to a wire dict.

    Drops ``None`` values and the read-only ``id`` field so the platform assigns
    the identifier on create. Nested subtotal dataclasses are converted too.
    """
    raw = asdict(obj) if is_dataclass(obj) else dict(obj)

    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k != "id" and v is not None}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return clean(raw)


class SuperPDPClient:
    """HTTP client for the Super PDP certified platform API.

    Handles OAuth2 client-credentials authentication and token caching.
    All methods raise ``frappe.ValidationError`` on API errors so callers
    can display clean user-facing messages.
    """

    BASE_URL = "https://api.superpdp.tech"

    # Event status_code → internal pa_status priority weights. "rejected" outranks
    # "error" so a terminal platform rejection dominates the derived status.
    _STATUS_WEIGHT = {"rejected": 5, "error": 4, "done": 3, "pending": 2, "sent": 1}

    # Status codes that always resolve to a specific internal status
    _CODE_MAP: dict[str, str] = {
        "api:created": "sent",
        "api:received": "pending",
        "ppf:003": "pending",  # transmitted to PPF
        "ppf:004": "done",     # accepted by PPF
        # French PPF lifecycle status codes (fr:NNN)
        "fr:200": "sent",      # Submitted
        "fr:201": "pending",   # Sent
        "fr:202": "pending",   # Received
        "fr:203": "pending",   # Made available
        "fr:208": "pending",   # On hold
        "fr:209": "done",      # Completed
        "fr:211": "done",      # Payment sent
        "fr:212": "done",      # Payment received
    }
    _DONE_CODES = {"fr:204", "fr:205", "fr:206"}  # Acknowledged / Accepted / Partly accepted
    # Terminal rejections (the document was refused by the PPF / recipient).
    _REJECTED_CODES = {"fr:210", "fr:213", "api:rejected", "ppf:005"}  # Refused / Rejected
    _ERROR_CODES = {"fr:207", "fr:501"}  # Disputed / Inadmissible

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = None,
        disable_pre_check: bool = False,
        auth_method: str = "client_credentials",
        refresh_token: str | None = None,
        on_token_refreshed=None,
    ):
        if not requests:
            frappe.throw(_("The 'requests' library is required for the SuperPDP integration."))
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = (base_url or self.BASE_URL).rstrip("/")
        # Sandbox / pré-production platforms skip the platform's pre-validation
        # checks on every invoice send.
        self._disable_pre_check = disable_pre_check
        # "client_credentials" (act as our own company) or "authorization_code"
        # (refresh-token grant after interactive onboarding).
        self._auth_method = auth_method or "client_credentials"
        self._refresh_token = refresh_token
        # Callback(token_dict) used to persist a rotated token after refresh.
        self._on_token_refreshed = on_token_refreshed
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    def _fetch_token(self) -> None:
        if self._auth_method == "authorization_code":
            self._refresh_access_token()
            return
        resp = requests.post(
            f"{self._base_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=30,
        )
        self._raise_for_status(resp)
        data = resp.json()
        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        # Subtract 60 s so we refresh before actual expiry
        self._token_expires_at = time.monotonic() + expires_in - 60

    def _refresh_access_token(self) -> None:
        """Exchange the stored refresh token for a fresh access token.

        Persists the (possibly rotated) tokens through ``on_token_refreshed`` so
        the next request — in this or another worker — reuses them.
        """
        if not self._refresh_token:
            frappe.throw(
                _("This platform uses interactive authentication but has no refresh token. Run the onboarding.")
            )
        resp = requests.post(
            f"{self._base_url}/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self._client_id,
                "refresh_token": self._refresh_token,
            },
            timeout=30,
        )
        self._raise_for_status(resp)
        data = resp.json()
        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._token_expires_at = time.monotonic() + expires_in - 60
        # A rotated refresh token replaces the old one for subsequent refreshes.
        if data.get("refresh_token"):
            self._refresh_token = data["refresh_token"]
        if self._on_token_refreshed:
            self._on_token_refreshed(data)

    def _token(self) -> str:
        if not self._access_token or time.monotonic() >= self._token_expires_at:
            self._fetch_token()
        return self._access_token

    # -- Interactive onboarding (authorization_code + PKCE) -------------------

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        """Return a ``(code_verifier, code_challenge)`` PKCE pair (S256)."""
        import base64
        import hashlib
        import secrets

        code_verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return code_verifier, code_challenge

    @classmethod
    def build_authorize_url(
        cls,
        *,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        base_url: str = None,
        company_number: str | None = None,
        company_number_scheme: str | None = None,
        login_hint: str | None = None,
    ) -> str:
        """Build the SuperPDP ``/oauth2/authorize`` URL for the consent redirect."""
        from urllib.parse import urlencode

        base = (base_url or cls.BASE_URL).rstrip("/")
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if company_number and company_number_scheme:
            params["superpdp_company_number"] = company_number
            params["superpdp_company_number_scheme"] = company_number_scheme
        if login_hint:
            params["login_hint"] = login_hint
        return f"{base}/oauth2/authorize?{urlencode(params)}"

    @classmethod
    def exchange_authorization_code(
        cls,
        *,
        client_id: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        base_url: str = None,
    ) -> dict:
        """Exchange an authorization code for the initial token set."""
        if not requests:
            frappe.throw(_("The 'requests' library is required for the SuperPDP integration."))
        base = (base_url or cls.BASE_URL).rstrip("/")
        resp = requests.post(
            f"{base}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            # Do not leak the code/secret; surface only the platform's error text.
            frappe.throw(_("Token exchange failed: {0}").format(resp.text[:300]))
        return resp.json()

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self._token()}"}
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, path: str, **kwargs) -> "requests.Response":
        url = f"{self._base_url}{path}"
        extra_headers = kwargs.pop("headers", {})
        resp = requests.request(
            method,
            url,
            headers={**self._headers(), **extra_headers},
            timeout=60,
            **kwargs,
        )
        self._raise_for_status(resp)
        return resp

    @staticmethod
    def _raise_for_status(resp: "requests.Response") -> None:
        if resp.ok:
            return
        try:
            body = resp.json()
            msg = body.get("message") or body.get("error") or resp.text[:300]
        except Exception:
            msg = resp.text[:300]

        if "Seller.LegalRegistrationIdentifier" in msg:
            frappe.throw(
                _(
                    "The seller's legal registration identifier (SIREN/SIRET) is missing from the e-invoice. "
                    "To fix this: <br>"
                    "1. Go to your <a href='/desk/company'>Company settings</a>.<br>"
                    "2. Ensure the <b>SIREN Number</b> field is filled.<br>"
                    "3. Re-save the invoice to regenerate the XML before trying again."
                ),
                frappe.ValidationError,
                title=_("Missing Seller Identifier")
            )

        low = msg.lower()
        if "receiver address does not exist" in low or "peppol directory" in low:
            frappe.throw(
                _(
                    "The recipient's routing address could not be found in the e-invoicing directory "
                    "(PPF/Peppol), so this invoice can't be delivered. The directory line resolved for "
                    "this customer may be out of date, or the establishment may not be registered. "
                    "To fix this: <br>"
                    "1. Re-sync the directory for this customer (Customer &rarr; e-invoicing &rarr; "
                    "<b>Sync directory</b>) so the active routing line reflects the current directory.<br>"
                    "2. Check the billing <b>Address SIRET</b> matches a registered establishment "
                    "(a SIRET is 14 digits) and that the recipient is live on an accredited platform (PDP).<br>"
                    "3. Re-save the Sales Invoice to regenerate the e-invoice, then retry."
                ),
                frappe.ValidationError,
                title=_("Recipient not reachable for e-invoicing"),
            )

        frappe.throw(
            _("SuperPDP API error {0}: {1}").format(resp.status_code, msg),
            frappe.ValidationError,
        )

    # -------------------------------------------------------------------------
    # Company / Session
    # -------------------------------------------------------------------------

    def get_company(self) -> dict:
        """Return the company bound to the current OAuth2 credentials."""
        return self._request("GET", "/v1.beta/companies/me").json()

    def healthcheck(self) -> None:
        """Probe connectivity by fetching the bound company (forces OAuth)."""
        self.get_company()

    def get_session_info(self) -> dict:
        """Return OAuth2 session metadata including KYB verification status."""
        return self._request("GET", "/v1.beta/oauth2_sessions/me").json()

    # -------------------------------------------------------------------------
    # Invoices (raw API)
    # -------------------------------------------------------------------------

    def send_invoice(
        self,
        file_content: bytes,
        filename: str,
        syntax: str,
        external_id: str = None,
        disable_pre_check: bool = False,
    ) -> dict:
        """POST an invoice file to Super PDP. Returns the created invoice object."""
        params: dict = {}
        if external_id:
            params["external_id"] = external_id[:36]
        if disable_pre_check:
            params["disable_pre_check"] = "true"
        resp = self._request(
            "POST",
            "/v1.beta/invoices",
            headers={"Content-Type": self._content_type(syntax)},
            params=params,
            data=file_content,
        )
        return resp.json()

    def list_invoices(
        self,
        direction: str = None,
        date: str = None,
        limit: int = None,
        starting_after_id: int = None,
    ) -> list[dict]:
        """List invoices, auto-paginating until all results are returned."""
        params: dict = {}
        if direction:
            params["direction"] = direction
        if date:
            params["date"] = date
        if limit:
            params["limit"] = limit

        all_items: list[dict] = []
        after_id = starting_after_id
        while True:
            if after_id is not None:
                params["starting_after_id"] = after_id
            resp = self._request("GET", "/v1.beta/invoices", params=params).json()
            page = resp.get("data", [])
            all_items.extend(page)
            if not resp.get("has_after") or not page:
                break
            after_id = page[-1]["id"]
        return all_items

    def get_invoice(self, invoice_id: int | str) -> dict:
        """Retrieve a single invoice with its events."""
        return self._request("GET", f"/v1.beta/invoices/{invoice_id}").json()

    def download_invoice(self, invoice_id: int | str) -> bytes:
        """Download the raw invoice file (PDF or XML)."""
        return self._request("GET", f"/v1.beta/invoices/{invoice_id}/download").content

    def validate_invoice(self, file_content: bytes, syntax: str) -> dict:
        """Validate an invoice against the Super PDP rules and return the report."""
        resp = self._request(
            "POST",
            "/v1.beta/validation_reports",
            headers={"Content-Type": self._content_type(syntax)},
            data=file_content,
        )
        return resp.json()

    # -------------------------------------------------------------------------
    # Invoice Events (raw API)
    # -------------------------------------------------------------------------

    def list_invoice_events(
        self,
        invoice_id: int = None,
        starting_after_id: int = None,
        limit: int = None,
    ) -> list[dict]:
        """List invoice lifecycle events, auto-paginating until all are returned.

        Filtered by invoice when ``invoice_id`` is given. Without pagination a
        long-lived invoice would silently drop events past the first page.
        """
        params: dict = {}
        if invoice_id is not None:
            params["invoice_id"] = invoice_id
        if limit:
            params["limit"] = limit

        all_items: list[dict] = []
        after_id = starting_after_id
        while True:
            if after_id is not None:
                params["starting_after_id"] = after_id
            resp = self._request("GET", "/v1.beta/invoice_events", params=params).json()
            page = resp.get("data", [])
            all_items.extend(page)
            if not resp.get("has_after") or not page:
                break
            after_id = page[-1]["id"]
        return all_items

    def create_invoice_event(
        self,
        invoice_id: int,
        status_code: str,
        details: list[dict] = None,
        attachments: list[dict] = None,
    ) -> dict:
        """Create a buyer-side lifecycle event (e.g. fr:204 acknowledgement)."""
        payload: dict = {"invoice_id": invoice_id, "status_code": status_code}
        if details:
            payload["details"] = details
        if attachments:
            payload["attachments"] = attachments
        return self._request("POST", "/v1.beta/invoice_events", json=payload).json()

    # -------------------------------------------------------------------------
    # French Directory (raw API)
    # -------------------------------------------------------------------------

    def list_french_directory_entries(self, siren: str) -> list[dict]:
        """Return all Peppol/PPF directory entries for a given SIREN."""
        resp = self._request(
            "GET",
            "/v1.beta/french_directory/entries",
            params={"number": siren},
        )
        return resp.json().get("data", [])

    def search_french_directory_companies(
        self,
        formal_name_starts_with: str = None,
        post_code_starts_with: str = None,
        number: str = None,
        limit: int = None,
    ) -> list[dict]:
        """Full-text search of companies registered in the French e-invoicing directory."""
        params: dict = {}
        if formal_name_starts_with:
            params["formal_name_starts_with"] = formal_name_starts_with
        if post_code_starts_with:
            params["post_code_starts_with"] = post_code_starts_with
        if number:
            params["number"] = number
        if limit:
            params["limit"] = limit
        return self._request(
            "GET", "/v1.beta/french_directory/companies", params=params
        ).json().get("data", [])

    # -------------------------------------------------------------------------
    # Own Directory Entries (raw API)
    # -------------------------------------------------------------------------

    def list_directory_entries(self) -> list[dict]:
        """List your own Peppol/PPF directory entries."""
        return self._request("GET", "/v1.beta/directory_entries").json().get("data", [])

    def create_directory_entry(self, identifier: str, directory: str) -> dict:
        """Register a new Peppol or PPF directory entry for your company.

        ``identifier``: Peppol address, e.g. ``"0225:853322915"``
        ``directory``: ``"peppol"`` or ``"ppf"``
        """
        return self._request(
            "POST",
            "/v1.beta/directory_entries",
            json={"identifier": identifier, "directory": directory},
        ).json()

    def delete_directory_entry(self, entry_id: int) -> None:
        """Remove a directory entry."""
        self._request("DELETE", f"/v1.beta/directory_entries/{entry_id}")

    def get_directory_entry(self, entry_id: int) -> dict:
        """Retrieve a single directory entry by id."""
        return self._request("GET", f"/v1.beta/directory_entries/{entry_id}").json()

    # -------------------------------------------------------------------------
    # Unified platform client interface (used by plateforme_agreee layer)
    # -------------------------------------------------------------------------

    def submit_invoice(
        self,
        file_content: bytes,
        filename: str,
        syntax: str,
        external_id: str = None,
        processing_rule: str = None,
        **_,
    ) -> FlowResult:
        """Send an invoice and return a platform-agnostic FlowResult."""
        res = self.send_invoice(
            file_content,
            filename,
            syntax,
            external_id=external_id,
            disable_pre_check=self._disable_pre_check,
        )
        return FlowResult(
            flow_id=str(res["id"]),
            submitted_at=_to_db_datetime(res.get("created_at")),
            syntax=syntax,
            flow_type="CustomerInvoice",
        )

    def get_invoice_status(self, flow_id: str) -> StatusResult:
        """Poll the latest status for a submitted invoice."""
        invoice = self.get_invoice(flow_id)
        events: list[dict] = invoice.get("events", [])
        status = self._derive_status(events)
        updated_at = _to_db_datetime(events[-1].get("created_at")) if events else None
        error_details = self._collect_error_details(events)
        return StatusResult(status=status, updated_at=updated_at, error_details=error_details)

    def list_incoming_invoices(self, updated_after: datetime = None) -> list[IncomingFlow]:
        """Fetch incoming invoices and return as platform-agnostic IncomingFlow list.

        ``updated_after`` narrows the query to the months it covers — the API's
        ``date`` filter is month-granular (e.g. ``2025-11``) — so hourly polls stop
        paging through the whole invoice history. The caller's dedup against known
        flow ids stays the correctness backstop.
        """
        if updated_after is None:
            invoices = self.list_invoices(direction="in")
        else:
            invoices = []
            for month in _months_between(updated_after, datetime.now()):
                invoices.extend(self.list_invoices(direction="in", date=month))
        return [
            IncomingFlow(
                flow_id=str(inv["id"]),
                submitted_at=_to_db_datetime(inv.get("created_at")),
                updated_at=_to_db_datetime(inv.get("created_at")),
                flow_type="SupplierInvoice",
                syntax=None,
            )
            for inv in invoices
        ]

    def download_flow(self, flow_id: str) -> bytes:
        """Download an invoice file by its platform flow_id."""
        return self.download_invoice(flow_id)

    def get_directory_for_siren(self, siren: str, directory_type: str = "ppf") -> DirectoryData:
        """Look up e-invoicing directory entries for a company by SIREN.

        ``directory_type``: ``"ppf"`` (French national directory) or ``"peppol"``.
        """
        directory_type = directory_type or "ppf"
        entries = self.list_french_directory_entries(siren)
        # Keep only entries for the requested directory. Entries without a
        # directory marker are retained so a schema change can't silently
        # empty the result.
        entries = [e for e in entries if e.get("directory", directory_type) == directory_type]
        if not entries:
            return DirectoryData(entity_type="no", name="", closed=False)

        first_company = entries[0].get("company", {})
        name = first_company.get("formal_name", "")
        any_active = any(e.get("is_active") for e in entries)
        # Administrative closure (entity ceased) is distinct from "no active
        # routing line": the former marks the legal entity as closed, the latter a
        # VAT-registered business whose directory entry is currently inactive.
        closed = (
            first_company.get("administrative_status") == "C"
            or bool(first_company.get("closed"))
            or bool(first_company.get("is_closed"))
        )

        lines: dict[str, DirectoryLineData] = {}
        for entry in entries:
            identifier = entry.get("identifier", "")
            if not identifier:
                continue
            lines[identifier] = DirectoryLineData(
                line_status="active" if entry.get("is_active") else "inactive",
                routing_code_name=identifier,
                commitment_required=False,
            )

        # A registered business with no active routing line is e-reported (B2C),
        # not e-invoiced — surface that as private_inactive (mirrors akretion).
        return DirectoryData(
            entity_type="private" if any_active else "private_inactive",
            name=name,
            closed=closed,
            lines=lines,
        )

    # -------------------------------------------------------------------------
    # Lifecycle status (unified interface)
    # -------------------------------------------------------------------------

    def submit_lifecycle_status(
        self,
        *,
        flow_id: str,
        status: str,
        einvoice=None,
        details: list[dict] = None,
        attachments: list[dict] = None,
    ) -> LifecycleResult:
        """Report a lifecycle status via SuperPDP's native event endpoint."""
        status_code = lifecycle_status.to_superpdp_code(status)
        res = self.create_invoice_event(
            int(flow_id),
            status_code,
            details=details,
            attachments=attachments,
        )
        return LifecycleResult(
            state="sent",
            event_id=str(res.get("id")) if res.get("id") is not None else None,
            submitted_at=_to_db_datetime(res.get("created_at")),
        )

    def list_incoming_lifecycle_flows(self) -> list[IncomingFlow]:
        """No separate lifecycle flows: SuperPDP exposes events inline on each
        invoice, read via ``get_lifecycle_events()``."""
        return []

    def get_lifecycle_events(self, flow_id: str) -> list[LifecycleEvent]:
        """Return the lifecycle events recorded on one of our outgoing invoices."""
        raw_events = self.list_invoice_events(invoice_id=int(flow_id))
        events: list[LifecycleEvent] = []
        for ev in raw_events:
            canonical = lifecycle_status.from_superpdp_code(ev.get("status_code", ""))
            if not canonical:
                continue
            comment = None
            details = ev.get("details") or []
            if details:
                comment = details[0].get("reason")
            events.append(
                LifecycleEvent(
                    status=canonical,
                    status_label=lifecycle_status.label(canonical),
                    direction="in",
                    datetime=_to_db_datetime(ev.get("created_at")),
                    comment=comment,
                    pa_event_id=str(ev.get("id")) if ev.get("id") is not None else None,
                )
            )
        return events

    # -------------------------------------------------------------------------
    # B2C e-reporting (data declared to the PPF)
    # -------------------------------------------------------------------------

    def create_b2c_transactions(self, transactions: list["B2CTransaction"]) -> list[dict]:
        """Create B2C transaction data (10.1 / 10.3 flows).

        Transactions are stored immediately, then aggregated and sent to the PPF
        on a schedule that depends on the company VAT regime.
        """
        payload = {"data": [_ereporting_payload(t) for t in transactions]}
        return self._request("POST", "/v1.beta/b2c_transactions", json=payload).json().get("data", [])

    def list_b2c_transactions(self) -> list[dict]:
        """List the B2C transactions previously created."""
        return self._paginate("/v1.beta/b2c_transactions")

    def create_b2c_payments(self, payments: list["B2CPayment"]) -> list[dict]:
        """Create B2C payment data (10.2 / 10.4 flows)."""
        payload = {"data": [_ereporting_payload(p) for p in payments]}
        return self._request("POST", "/v1.beta/b2c_payments", json=payload).json().get("data", [])

    def list_b2c_payments(self) -> list[dict]:
        """List the B2C payments previously created."""
        return self._paginate("/v1.beta/b2c_payments")

    def update_vat_regime(self, vat_regime: str) -> dict:
        """Set the company VAT regime, which drives the PPF declaration schedule.

        ``vat_regime`` is one of: ``monthly``, ``quarterly``, ``simplified``,
        ``vat_exemption``.
        """
        return self._request(
            "PATCH", "/v1.beta/companies", json={"vat_regime": vat_regime}
        ).json()

    def list_ereportings(self, role_code: str = None) -> list[EreportingResult]:
        """List e-reporting declarations sent to the PPF (optionally one side)."""
        params = {"role_code": role_code} if role_code else None
        raw = self._paginate("/v1.beta/ereportings", params=params)
        return [self._to_ereporting(r) for r in raw]

    def get_ereporting(self, ereporting_id: int | str) -> EreportingResult:
        """Retrieve a single e-reporting declaration by id."""
        raw = self._request("GET", f"/v1.beta/ereportings/{ereporting_id}").json()
        return self._to_ereporting(raw)

    def preview_ereporting(self, kind: str, date: str, role_code: str) -> dict:
        """Preview the e-reporting data that will be sent for a period.

        ``kind`` is ``transaction`` or ``payment``; ``date`` is any date inside
        the wanted period; ``role_code`` is ``SE`` or ``BY``.
        """
        return self._request(
            "GET",
            "/v1.beta/ereportings/preview",
            params={"kind": kind, "date": date, "role_code": role_code},
        ).json()

    @staticmethod
    def _to_ereporting(raw: dict) -> EreportingResult:
        return EreportingResult(
            id=str(raw.get("id")),
            kind=raw.get("kind", ""),
            role_code=raw.get("role_code", ""),
            start_period=raw.get("start_period"),
            end_period=raw.get("end_period"),
            events=[
                EreportingEvent(
                    status_code=ev.get("status_code", ""),
                    created_at=_to_db_datetime(ev.get("created_at")),
                )
                for ev in raw.get("events", [])
            ],
        )

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _paginate(self, path: str, params: dict | None = None) -> list[dict]:
        """GET a list endpoint, following ``has_after`` / ``starting_after_id``."""
        params = dict(params or {})
        all_items: list[dict] = []
        after_id = None
        while True:
            if after_id is not None:
                params["starting_after_id"] = after_id
            resp = self._request("GET", path, params=params).json()
            page = resp.get("data", [])
            all_items.extend(page)
            if not resp.get("has_after") or not page:
                break
            after_id = page[-1]["id"]
        return all_items

    def _derive_status(self, events: list[dict]) -> str:
        """Derive a single pa_status value from the append-only events list."""
        if not events:
            return "sent"
        best = "sent"
        for ev in events:
            code = ev.get("status_code", "")
            status = self._map_code(code)
            if self._STATUS_WEIGHT.get(status, 0) > self._STATUS_WEIGHT.get(best, 0):
                best = status
        return best

    def _map_code(self, code: str) -> str:
        if code in self._DONE_CODES:
            return "done"
        if code in self._REJECTED_CODES:
            return "rejected"
        if code in self._ERROR_CODES:
            return "error"
        return self._CODE_MAP.get(code, "pending")

    def _collect_error_details(self, events: list[dict]) -> str | None:
        reasons = []
        for ev in events:
            if self._map_code(ev.get("status_code", "")) in ("error", "rejected"):
                for detail in ev.get("details", []):
                    reason = detail.get("reason") or detail.get("message")
                    if reason:
                        reasons.append(reason)
                ev_reason = ev.get("data", {}).get("reason")
                if ev_reason and ev_reason not in reasons:
                    reasons.append(ev_reason)
        return "; ".join(reasons) if reasons else None

    @staticmethod
    def _content_type(syntax: str) -> str:
        return "application/pdf" if syntax == "Factur-X" else "application/xml"
