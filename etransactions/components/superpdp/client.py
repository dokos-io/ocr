"""SuperPDP API client.

Implements the unified platform client interface (send_invoice, get_invoice_status,
list_incoming_invoices, download_invoice, get_directory_for_siren) required by
etransactions.plateforme_agreee, plus direct access to all SuperPDP API endpoints.

API reference: https://api.superpdp.tech (OpenAPI spec: components/ext/superpdp.json)
"""

import time

import frappe
from frappe import _

from etransactions.components.superpdp.models import (
    DirectoryData,
    DirectoryLineData,
    FlowResult,
    IncomingFlow,
    StatusResult,
)

try:
    import requests
except ImportError:
    requests = None


class SuperPDPClient:
    """HTTP client for the Super PDP certified platform API.

    Handles OAuth2 client-credentials authentication and token caching.
    All methods raise ``frappe.ValidationError`` on API errors so callers
    can display clean user-facing messages.
    """

    BASE_URL = "https://api.superpdp.tech"

    # Event status_code → internal pa_status priority weights
    _STATUS_WEIGHT = {"error": 4, "done": 3, "pending": 2, "sent": 1}

    # Status codes that always resolve to a specific internal status
    _CODE_MAP: dict[str, str] = {
        "api:created": "sent",
        "api:received": "pending",
        "api:rejected": "error",
        "ppf:003": "pending",  # transmitted to PPF
        "ppf:004": "done",     # accepted by PPF
        "ppf:005": "error",    # rejected by PPF
    }
    _DONE_CODES = {"fr:204", "fr:205", "fr:206"}
    _ERROR_CODES = {"fr:207", "api:rejected", "ppf:005"}

    def __init__(self, client_id: str, client_secret: str, base_url: str = None):
        if not requests:
            frappe.throw(_("The 'requests' library is required for the SuperPDP integration."))
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = (base_url or self.BASE_URL).rstrip("/")
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    def _fetch_token(self) -> None:
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

    def _token(self) -> str:
        if not self._access_token or time.monotonic() >= self._token_expires_at:
            self._fetch_token()
        return self._access_token

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
        """List invoice lifecycle events, optionally filtered by invoice."""
        params: dict = {}
        if invoice_id is not None:
            params["invoice_id"] = invoice_id
        if starting_after_id is not None:
            params["starting_after_id"] = starting_after_id
        if limit:
            params["limit"] = limit
        return self._request("GET", "/v1.beta/invoice_events", params=params).json().get("data", [])

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
        )
        return FlowResult(
            flow_id=str(res["id"]),
            submitted_at=res.get("created_at"),
            syntax=syntax,
            flow_type="CustomerInvoice",
        )

    def get_invoice_status(self, flow_id: str) -> StatusResult:
        """Poll the latest status for a submitted invoice."""
        invoice = self.get_invoice(flow_id)
        events: list[dict] = invoice.get("events", [])
        status = self._derive_status(events)
        updated_at = events[-1].get("created_at") if events else None
        error_details = self._collect_error_details(events)
        return StatusResult(status=status, updated_at=updated_at, error_details=error_details)

    def list_incoming_invoices(self) -> list[IncomingFlow]:
        """Fetch all incoming invoices and return as platform-agnostic IncomingFlow list."""
        invoices = self.list_invoices(direction="in")
        return [
            IncomingFlow(
                flow_id=str(inv["id"]),
                submitted_at=inv.get("created_at"),
                updated_at=inv.get("created_at"),
                flow_type="SupplierInvoice",
                syntax=None,
            )
            for inv in invoices
        ]

    def download_flow(self, flow_id: str) -> bytes:
        """Download an invoice file by its platform flow_id."""
        return self.download_invoice(flow_id)

    def get_directory_for_siren(self, siren: str) -> DirectoryData:
        """Look up e-invoicing directory entries for a company by SIREN."""
        entries = self.list_french_directory_entries(siren)
        if not entries:
            return DirectoryData(entity_type="no", name="", closed=False)

        first_company = entries[0].get("company", {})
        name = first_company.get("formal_name", "")
        all_inactive = all(not e.get("is_active") for e in entries)

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

        return DirectoryData(
            entity_type="private",
            name=name,
            closed=all_inactive,
            lines=lines,
        )

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

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
        if code in self._ERROR_CODES:
            return "error"
        return self._CODE_MAP.get(code, "pending")

    def _collect_error_details(self, events: list[dict]) -> str | None:
        reasons = []
        for ev in events:
            if self._map_code(ev.get("status_code", "")) == "error":
                for detail in ev.get("details", []):
                    reason = detail.get("reason")
                    if reason:
                        reasons.append(reason)
                ev_reason = ev.get("data", {}).get("reason")
                if ev_reason and ev_reason not in reasons:
                    reasons.append(ev_reason)
        return "; ".join(reasons) if reasons else None

    @staticmethod
    def _content_type(syntax: str) -> str:
        return "application/pdf" if syntax == "Factur-X" else "application/xml"
