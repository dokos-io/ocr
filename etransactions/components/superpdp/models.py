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
    entity_type: str  # private | private_inactive | public | no
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


# ---------------------------------------------------------------------------
# B2C e-reporting (data declared to the PPF, not invoice flows)
# ---------------------------------------------------------------------------


@dataclass
class B2CTransactionSubtotal:
    """A per-rate VAT breakdown line of a B2C transaction (Z12-012 Annex A)."""
    tax_percent: str
    taxable_amount: str
    tax_total: str


@dataclass
class B2CTransaction:
    """Normalized B2C transaction (10.1 / 10.3 flow) for e-reporting.

    ``role_code`` is ``SE`` (we are the seller) or ``BY`` (we are the buyer).
    ``category_code`` is the Z12-012 transaction category (TLB1/TPS1/TNT1/TMA1).
    ``id`` is the platform-assigned identifier, set only on read-back.
    """
    date: str
    currency: str
    category_code: str
    tax_exclusive_amount: str
    tax_total: str
    tax_subtotals: list = field(default_factory=list)  # B2CTransactionSubtotal
    role_code: str = "SE"
    tax_due_date_type_code: str | None = None
    id: str | None = None


@dataclass
class B2CPaymentSubtotal:
    """A per-rate breakdown line of a B2C payment (10.2 / 10.4 flow)."""
    amount: str
    tax_percent: str
    category_code: str | None = None
    currency_code: str | None = None


@dataclass
class B2CPayment:
    """Normalized B2C payment data (10.2 / 10.4 flow) for e-reporting."""
    date: str
    subtotals: list = field(default_factory=list)  # B2CPaymentSubtotal
    id: str | None = None


@dataclass
class EreportingEvent:
    """A status event on a PPF e-reporting declaration."""
    status_code: str  # ppf:ereporting / -ack / -ack-error / -rejected / -response-ok
    created_at: str | None = None


@dataclass
class EreportingResult:
    """Normalized PPF e-reporting declaration (aggregated by the platform).

    ``kind`` is ``transaction`` or ``payment``; ``role_code`` is ``SE`` or
    ``BY``; ``events`` is the ordered list of PPF acknowledgement events.
    """
    id: str
    kind: str
    role_code: str
    start_period: str | None = None
    end_period: str | None = None
    events: list = field(default_factory=list)  # EreportingEvent
