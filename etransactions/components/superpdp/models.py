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
