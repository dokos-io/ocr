from dataclasses import dataclass, field


@dataclass
class FlowResult:
    """Normalized result after sending an invoice to any accredited platform."""
    flow_id: str
    submitted_at: str | None
    syntax: str
    flow_type: str = "CustomerInvoice"


@dataclass
class StatusResult:
    """Normalized current status of a flow on any accredited platform."""
    status: str  # sent | pending | done | error
    updated_at: str | None = None
    error_details: str | None = None


@dataclass
class IncomingFlow:
    """Normalized description of an incoming invoice flow from any platform."""
    flow_id: str
    submitted_at: str | None
    updated_at: str | None
    flow_type: str
    syntax: str | None


@dataclass
class DirectoryLineData:
    line_status: str  # active | inactive | disabled
    routing_code_name: str
    commitment_required: bool = False


@dataclass
class DirectoryData:
    """Normalized directory lookup result for a SIREN from any platform."""
    entity_type: str  # private | public | no
    name: str
    closed: bool
    lines: dict = field(default_factory=dict)  # identifier -> DirectoryLineData


@dataclass
class LifecycleResult:
    """Normalized result after submitting a lifecycle status to any platform.

    ``event_id`` is set for platforms with a native event endpoint (SuperPDP);
    ``flow_id`` is set for platforms that carry the status as a CDAR flow
    (Esalink / AFNOR). Exactly one of the two is populated.
    """
    state: str  # created | sent | done | error
    event_id: str | None = None
    flow_id: str | None = None
    submitted_at: str | None = None


@dataclass
class LifecycleEvent:
    """Normalized lifecycle status event read from any platform."""
    status: str  # canonical status (etransactions.plateforme_agreee.lifecycle_status)
    status_label: str
    direction: str  # in | out
    datetime: str | None = None
    reason_code: str | None = None
    reason_text: str | None = None
    action_code: str | None = None
    action_text: str | None = None
    comment: str | None = None
    amount: float | None = None
    currency: str | None = None
    payment_date: str | None = None
    pa_event_id: str | None = None
    attachments: list = field(default_factory=list)
