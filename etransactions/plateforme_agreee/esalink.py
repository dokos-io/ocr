"""ESALINKClient — wraps a pyfrctc session to implement the unified PA client interface.

This adapter lets flow.py, directory.py and einvoice.py remain platform-agnostic:
they only call the interface methods (submit_invoice, get_invoice_status, etc.)
and do not need to know whether the underlying PA is Esalink or Super PDP.
"""

import frappe
from frappe import _

from etransactions.components.superpdp.models import (
    DirectoryData,
    DirectoryLineData,
    FlowResult,
    IncomingFlow,
    LifecycleEvent,
    LifecycleResult,
    StatusResult,
)
from etransactions.plateforme_agreee.cdar import generate_cdar_flow


class ESALINKClient:
    """Adapts a ``pyfrctc`` session to the unified eTransactions PA client interface."""

    def __init__(self, pyfrctc_session):
        self._session = pyfrctc_session

    def healthcheck(self) -> None:
        """Probe connectivity using pyfrctc's healthcheck on the session."""
        from pyfrctc import healthcheck as _healthcheck

        _healthcheck(self._session)

    # -------------------------------------------------------------------------
    # Unified platform client interface
    # -------------------------------------------------------------------------

    def submit_invoice(
        self,
        file_content: bytes,
        filename: str,
        syntax: str,
        external_id: str = None,
        processing_rule: str = "B2B",
        **_,
    ) -> FlowResult:
        try:
            from pyfrctc import send_flow_parsed
        except ImportError:
            frappe.throw(_("The pyfrctc library is not installed."))

        res = send_flow_parsed(self._session, file_content, filename, syntax, processing_rule)
        return FlowResult(
            flow_id=res.get("flowId", ""),
            submitted_at=res.get("submittedAt"),
            syntax=syntax,
            flow_type="CustomerInvoice",
        )

    def get_invoice_status(self, flow_id: str) -> StatusResult:
        try:
            from pyfrctc import get_flow_metadata_parsed
        except ImportError:
            frappe.throw(_("The pyfrctc library is not installed."))

        res = get_flow_metadata_parsed(self._session, flow_id)
        return StatusResult(
            status=res.get("state", "pending"),
            updated_at=res.get("updatedAt"),
            error_details=res.get("ap_error_details"),
        )

    def list_incoming_invoices(self) -> list[IncomingFlow]:
        try:
            from pyfrctc import search_flows
        except ImportError:
            frappe.throw(_("The pyfrctc library is not installed."))

        raw_flows = search_flows(self._session, direction="In") or []
        return [
            IncomingFlow(
                flow_id=f.get("flowId", ""),
                submitted_at=f.get("submittedAt"),
                updated_at=f.get("updatedAt") or f.get("submittedAt"),
                flow_type=f.get("flowType", "SupplierInvoice"),
                syntax=f.get("flowSyntax"),
            )
            for f in raw_flows
        ]

    def download_flow(self, flow_id: str) -> bytes:
        try:
            from pyfrctc import get_flow
        except ImportError:
            frappe.throw(_("The pyfrctc library is not installed."))

        return get_flow(self._session, flow_id, doc_type="Original")

    def submit_lifecycle_status(
        self,
        *,
        flow_id: str,
        status: str,
        einvoice,
        details: list[dict] = None,
        attachments: list[dict] = None,
        processing_rule: str = "B2B",
    ) -> LifecycleResult:
        """Report a lifecycle status by submitting a CDAR flow via pyfrctc."""
        try:
            from pyfrctc import send_flow_parsed
        except ImportError:
            frappe.throw(_("The pyfrctc library is not installed."))

        cdar_bytes, filename = generate_cdar_flow(einvoice, status, details, attachments)
        res = send_flow_parsed(self._session, cdar_bytes, filename, "CDAR", processing_rule)
        return LifecycleResult(
            state="sent",
            flow_id=res.get("flowId"),
            submitted_at=res.get("submittedAt"),
        )

    def list_incoming_lifecycle_flows(self) -> list[IncomingFlow]:
        """Return incoming lifecycle (CDAR) flows from the last 30 days."""
        try:
            from pyfrctc import search_flows_parsed
        except ImportError:
            frappe.throw(_("The pyfrctc library is not installed."))

        import datetime as _dt

        updated_after = (
            _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=30)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        raw_flows = search_flows_parsed(
            self._session,
            updated_after,
            flow_direction="in",
            flow_type=["CustomerInvoiceLC", "SupplierInvoiceLC"],
        ) or []
        return [
            IncomingFlow(
                flow_id=f.get("flowId", ""),
                submitted_at=f.get("submittedAt"),
                updated_at=f.get("updatedAt") or f.get("submittedAt"),
                flow_type=f.get("flowType", "CustomerInvoiceLC"),
                syntax=f.get("flowSyntax"),
            )
            for f in raw_flows
        ]

    def get_lifecycle_events(self, flow_id: str) -> list[LifecycleEvent]:
        """No-op for Esalink: lifecycle CDARs arrive as separate ``*InvoiceLC``
        flows and are processed by ``flow.poll_incoming_lifecycle_flows()``."""
        return []

    def get_directory_for_siren(self, siren: str, directory_type: str = "ppf") -> DirectoryData:
        # Esalink/CDAR exposes only the French national directory; directory_type
        # is accepted for interface parity and currently ignored.
        try:
            from pyfrctc import get_directory_siren_parsed, get_directory_lines_parsed
        except ImportError:
            frappe.throw(_("The pyfrctc library is not installed."))

        siren_parsed = get_directory_siren_parsed(self._session, siren)
        entity_type = siren_parsed.get("entity_type", "no")
        name = siren_parsed.get("name") or ""
        closed = bool(siren_parsed.get("closed"))

        lines: dict[str, DirectoryLineData] = {}
        if entity_type != "no" and not closed:
            raw_lines: dict = get_directory_lines_parsed(self._session, siren, siren_parsed)
            for identifier, vals in raw_lines.items():
                lines[identifier] = DirectoryLineData(
                    line_status=vals.get("line_status", "inactive"),
                    routing_code_name=vals.get("routing_code_name", identifier),
                    commitment_required=bool(vals.get("commitment_required", False)),
                )

        return DirectoryData(entity_type=entity_type, name=name, closed=closed, lines=lines)

    # -------------------------------------------------------------------------
    # B2C e-reporting — not supported on Esalink/CDAR platforms
    # -------------------------------------------------------------------------

    @staticmethod
    def _ereporting_unsupported():
        frappe.throw(_("B2C e-reporting is not supported on this platform."))

    def create_b2c_transactions(self, transactions):
        self._ereporting_unsupported()

    def list_b2c_transactions(self):
        self._ereporting_unsupported()

    def create_b2c_payments(self, payments):
        self._ereporting_unsupported()

    def list_b2c_payments(self):
        self._ereporting_unsupported()

    def update_vat_regime(self, vat_regime: str):
        self._ereporting_unsupported()

    def list_ereportings(self, role_code: str = None):
        self._ereporting_unsupported()

    def get_ereporting(self, ereporting_id):
        self._ereporting_unsupported()

    def preview_ereporting(self, kind: str, date: str, role_code: str):
        self._ereporting_unsupported()
