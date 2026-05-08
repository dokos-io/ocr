"""AFNORClient — generic HTTP client for any AFNOR XP Z12-013 compliant PA.

Implements the unified platform client interface required by plateforme_agreee,
directly against the standard REST API endpoints defined in the AFNOR spec
(Flows, Directory) so any compliant PA can be used without a vendor SDK.

Auth: OAuth2 client_credentials via POST /v1/oauth2/token with credentials
      passed as query parameters (as specified in the AFNOR/Esalink YAMLs).

The base URL is taken from the `api_base_url` field of the
eTransactions Accredited Platform document, making it fully configurable
per provider.
"""

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

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


class AFNORClient:
    """HTTP client for any AFNOR XP Z12-013 compliant Plateforme Agréée.

    The PA base URL is provided at construction time so the same class covers
    Esalink (HUBTIMIZE), and any other certified platform that implements the
    standard.  Token caching avoids repeated auth round-trips within a single
    request cycle.
    """

    # AFNOR-standard paths
    _TOKEN_PATH = "/v1/oauth2/token"
    _FLOWS_PATH = "/v1/flows"
    _FLOWS_SEARCH_PATH = "/v1/flows/search"
    _SIREN_PATH = "/v1/siren/code-insee:{siren}"
    _DIRECTORY_LINE_SEARCH_PATH = "/v1/directory-line/search"

    # Acknowledgement status → internal pa_status
    _ACK_STATUS_MAP = {
        "Pending": "pending",
        "Ok": "done",
        "Error": "error",
    }

    # AFNOR entityType → our entity_type
    _ENTITY_TYPE_MAP = {
        "Public": "public",
        "PrivateVatRegistered": "private",
    }

    # directoryLineStatus → line_status
    _LINE_STATUS_MAP = {
        "Enabled": "active",
        "Disabled": "inactive",
        "Upcoming": "inactive",
    }

    def __init__(self, client_id: str, client_secret: str, base_url: str):
        if not base_url:
            frappe.throw(_("An API base URL must be configured for Custom AFNOR platforms."))
        if not requests:
            frappe.throw(_("The 'requests' library is required for the AFNOR client."))
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    def _fetch_token(self) -> None:
        """Acquire a new OAuth2 access token using client credentials."""
        resp = requests.post(
            f"{self._base_url}{self._TOKEN_PATH}",
            params={
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

    def _request_or_none(self, method: str, path: str, **kwargs) -> "requests.Response | None":
        """Like _request but returns None on 404 instead of raising."""
        url = f"{self._base_url}{path}"
        extra_headers = kwargs.pop("headers", {})
        resp = requests.request(
            method,
            url,
            headers={**self._headers(), **extra_headers},
            timeout=60,
            **kwargs,
        )
        if resp.status_code == 404:
            return None
        self._raise_for_status(resp)
        return resp

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
        frappe.throw(
            _("AFNOR PA API error {0}: {1}").format(resp.status_code, msg),
            frappe.ValidationError,
        )

    # -------------------------------------------------------------------------
    # Flows (raw API)
    # -------------------------------------------------------------------------

    def submit_flow(
        self,
        file_content: bytes,
        filename: str,
        syntax: str,
        tracking_id: str = None,
        processing_rule: str = None,
    ) -> dict:
        """POST a flow file to the PA (multipart/form-data). Returns the FullFlowInfo dict."""
        flow_info: dict = {
            "name": filename,
            "flowSyntax": syntax,
            "sha256": hashlib.sha256(file_content).hexdigest(),
        }
        if tracking_id:
            flow_info["trackingId"] = tracking_id[:36]
        if processing_rule:
            flow_info["processingRule"] = processing_rule

        resp = self._request(
            "POST",
            self._FLOWS_PATH,
            files={
                "flowInfo": (None, json.dumps(flow_info), "application/json"),
                "file": (filename, file_content, "application/octet-stream"),
            },
        )
        return resp.json()

    def get_flow_metadata(self, flow_id: str) -> dict:
        """Retrieve flow metadata (acknowledgement status, timestamps, etc.)."""
        resp = self._request(
            "GET",
            f"{self._FLOWS_PATH}/{flow_id}",
            params={"docType": "Metadata"},
        )
        return resp.json()

    def download_flow_file(self, flow_id: str) -> bytes:
        """Download the original invoice file for a flow."""
        return self._request(
            "GET",
            f"{self._FLOWS_PATH}/{flow_id}",
            params={"docType": "Original"},
        ).content

    def search_flows(
        self,
        directions: list[str] = None,
        flow_types: list[str] = None,
        updated_after: str = None,
        updated_before: str = None,
        limit: int = 100,
    ) -> list[dict]:
        """POST /v1/flows/search. ``updated_after`` is required by the AFNOR spec."""
        if not updated_after:
            updated_after = (
                datetime.now(timezone.utc) - timedelta(days=30)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

        where: dict = {"updatedAfter": updated_after}
        if directions:
            where["flowDirection"] = directions
        if flow_types:
            where["flowType"] = flow_types
        if updated_before:
            where["updatedBefore"] = updated_before

        resp = self._request(
            "POST",
            self._FLOWS_SEARCH_PATH,
            json={"where": where, "limit": limit},
        )
        return resp.json().get("results", [])

    # -------------------------------------------------------------------------
    # Directory (raw API)
    # -------------------------------------------------------------------------

    def get_siren(self, siren: str) -> dict | None:
        """GET /v1/siren/code-insee:{siren}. Returns None if not found."""
        resp = self._request_or_none(
            "GET",
            self._SIREN_PATH.format(siren=siren),
        )
        return resp.json() if resp else None

    def search_directory_lines(self, siren: str, limit: int = 100) -> list[dict]:
        """POST /v1/directory-line/search filtered by SIREN."""
        body = {
            "filters": {"siren": {"op": "strict", "value": siren}},
            "include": ["routingCode"],
            "limit": limit,
        }
        resp = self._request("POST", self._DIRECTORY_LINE_SEARCH_PATH, json=body)
        return resp.json().get("results", [])

    # -------------------------------------------------------------------------
    # Unified platform client interface
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
        res = self.submit_flow(
            file_content,
            filename,
            syntax,
            tracking_id=external_id,
            processing_rule=processing_rule,
        )
        return FlowResult(
            flow_id=res.get("flowId", ""),
            submitted_at=res.get("submittedAt"),
            syntax=res.get("flowSyntax") or syntax,
            flow_type="CustomerInvoice",
        )

    def get_invoice_status(self, flow_id: str) -> StatusResult:
        """Poll the latest acknowledgement status for a submitted flow."""
        metadata = self.get_flow_metadata(flow_id)
        ack = metadata.get("acknowledgement") or {}
        ack_status = ack.get("status", "Pending")
        status = self._ACK_STATUS_MAP.get(ack_status, "pending")
        updated_at = metadata.get("updatedAt")
        error_details = self._collect_error_details(ack) if ack_status == "Error" else None
        return StatusResult(status=status, updated_at=updated_at, error_details=error_details)

    def list_incoming_invoices(self) -> list[IncomingFlow]:
        """Return all incoming SupplierInvoice flows from the last 30 days."""
        results = self.search_flows(
            directions=["In"],
            flow_types=["SupplierInvoice"],
        )
        return [
            IncomingFlow(
                flow_id=f.get("flowId", ""),
                submitted_at=f.get("submittedAt"),
                updated_at=f.get("updatedAt"),
                flow_type=f.get("flowType", "SupplierInvoice"),
                syntax=f.get("flowSyntax"),
            )
            for f in results
        ]

    def download_flow(self, flow_id: str) -> bytes:
        """Download an invoice file by its flow ID."""
        return self.download_flow_file(flow_id)

    def get_directory_for_siren(self, siren: str) -> DirectoryData:
        """Look up e-invoicing directory entries for a company by SIREN."""
        siren_data = self.get_siren(siren)
        if siren_data is None:
            return DirectoryData(entity_type="no", name="", closed=False)

        entity_type = self._ENTITY_TYPE_MAP.get(siren_data.get("entityType", ""), "no")
        name = siren_data.get("businessName", "")
        closed = siren_data.get("administrativeStatus") == "C"

        lines: dict[str, DirectoryLineData] = {}
        if entity_type != "no" and not closed:
            for result in self.search_directory_lines(siren):
                identifier = result.get("addressingIdentifier", "")
                if not identifier:
                    continue
                line_status = self._LINE_STATUS_MAP.get(
                    result.get("directoryLineStatus", ""), "inactive"
                )
                routing = result.get("routingCode") or {}
                lines[identifier] = DirectoryLineData(
                    line_status=line_status,
                    routing_code_name=routing.get("routingCodeName", identifier),
                    commitment_required=bool(routing.get("managesLegalCommitment", False)),
                )

        return DirectoryData(entity_type=entity_type, name=name, closed=closed, lines=lines)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _collect_error_details(ack: dict) -> str | None:
        reasons = [
            d.get("reasonMessage", "")
            for d in ack.get("details", [])
            if d.get("reasonMessage")
        ]
        return "; ".join(reasons) if reasons else None
