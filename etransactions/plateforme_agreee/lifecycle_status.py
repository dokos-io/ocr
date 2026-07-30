"""Canonical lifecycle status (statuts du cycle de vie) registry and mappings.

The French e-invoicing reform requires invoice lifecycle statuses to be reported
back through the accredited platform. Each platform speaks a different wire
protocol:

- **SuperPDP** uses ``fr:NNN`` event status codes on its native event endpoint.
- **Esalink / AFNOR** use CDAR XML, where the status is carried by ``MDT-105``
  (the AFNOR lifecycle status code) and ``MDT-88`` (the UN/CEFACT
  ProcessConditionCode).

This module defines a single canonical status string (matching the Odoo
``fr.einvoicing.event`` ``str_code`` values for cross-referencing) and the
mapping to each platform's representation. Higher-level code always works with
the canonical string; the clients translate it on the wire.

Reference: ``~/einvoicing-fr/fr-einvoicing/l10n_fr_einvoicing/models/fr_einvoicing_event.py``
"""

from frappe import _


# canonical str_code -> status definition
#   mdt105            : AFNOR lifecycle status code (CDAR MDT-105)
#   mdt88             : UN/CEFACT ProcessConditionCode (CDAR MDT-88)
#   superpdp          : SuperPDP native event status code, or None if unsupported
#   side              : "purchase" (buyer emits), "sale" (seller emits) or None (both/auto)
#   detail_required   : a reason/detail must accompany the status
#   confirm_required  : the UI should confirm before sending (irreversible)
#   repeatable        : the same status may legitimately be reported more than once
#   warning           : an incoming event with this status should raise a ToDo
STATUSES: dict[str, dict] = {
    "in_hand": {
        "mdt105": "204", "mdt88": "45", "superpdp": "fr:204",
        "side": "purchase", "decoration": "info",
    },
    "approved": {
        "mdt105": "205", "mdt88": "1", "superpdp": "fr:205",
        "side": "purchase", "decoration": "success",
    },
    "partially_approved": {
        "mdt105": "206", "mdt88": "49", "superpdp": "fr:206",
        "side": "purchase", "detail_required": True, "repeatable": True,
        "decoration": "warning",
    },
    "dispute": {
        "mdt105": "207", "mdt88": "46", "superpdp": "fr:207",
        "side": "purchase", "detail_required": True, "repeatable": True,
        "warning": True, "decoration": "warning",
    },
    "suspended": {
        "mdt105": "208", "mdt88": "39", "superpdp": None,
        "side": "purchase", "detail_required": True, "repeatable": True,
        "warning": True, "decoration": "warning",
    },
    "completed": {
        "mdt105": "209", "mdt88": "37", "superpdp": None,
        "side": "sale", "decoration": "info",
    },
    "refused": {
        "mdt105": "210", "mdt88": "50", "superpdp": None,
        "side": "purchase", "detail_required": True, "confirm_required": True,
        "warning": True, "decoration": "danger",
    },
    "payment_sent": {
        "mdt105": "211", "mdt88": "47", "superpdp": None,
        "side": "purchase", "repeatable": True, "decoration": "success",
    },
    "payment_received": {
        "mdt105": "212", "mdt88": "47", "superpdp": None,
        "side": "sale", "repeatable": True, "decoration": "success",
    },
    "cancelled": {
        "mdt105": "220", "mdt88": None, "superpdp": None,
        "side": None, "decoration": "danger",
    },
}

# Human-readable labels, translatable. Kept separate so they are picked up by
# the translation tooling and stay out of the plain data table above.
LABELS: dict[str, str] = {
    "in_hand": _("In Hand"),
    "approved": _("Approved"),
    "partially_approved": _("Partially Approved"),
    "dispute": _("Disputed"),
    "suspended": _("Suspended"),
    "completed": _("Completed"),
    "refused": _("Refused"),
    "payment_sent": _("Payment Sent"),
    "payment_received": _("Payment Received"),
    "cancelled": _("Cancelled"),
}

# Extra confirmation prompt for the irreversible statuses (``confirm_required``).
# Kept next to LABELS so the translation tooling picks it up, and served to the
# client so the wording lives in one place instead of being duplicated in JS.
CONFIRM_MESSAGES: dict[str, str] = {
    "refused": _(
        "Refusal is definitive and cannot be undone. To block the invoice temporarily"
        " instead (e.g. pending a correction), report 'Disputed'. Continue with the refusal?"
    ),
}

# Official CTC reason codes (MDT-113) allowed per status, extracted from the
# CDAR schematron (BR-FR-CDV-CL-09). A reason code is *required* for these
# statuses; sending one outside the list fails platform validation.
REASON_CODES: dict[str, list[str]] = {
	"partially_approved": [  # 206
		"AUTRE", "CMD_ERR", "SIRET_ERR", "CODE_ROUTAGE_ERR", "REF_CT_ABSENT",
		"REF_ERR", "PU_ERR", "REM_ERR", "QTE_ERR", "ART_ERR", "MODPAI_ERR",
		"QUALITE_ERR", "LIVR_INCOMP",
	],
	"dispute": [  # 207
		"AUTRE", "COORD_BANC_ERR", "TX_TVA_ERR", "MONTANTTOTAL_ERR", "CALCUL_ERR",
		"NON_CONFORME", "DOUBLON", "DEST_INC", "DEST_ERR", "TRANSAC_INC",
		"EMMET_INC", "CONTRAT_TERM", "DOUBLE_FACT", "CMD_ERR", "ADR_ERR",
		"SIRET_ERR", "CODE_ROUTAGE_ERR", "REF_CT_ABSENT", "REF_ERR", "PU_ERR",
		"REM_ERR", "QTE_ERR", "ART_ERR", "MODPAI_ERR", "QUALITE_ERR", "LIVR_INCOMP",
	],
	"suspended": [  # 208
		"JUSTIF_ABS", "COORD_BANC_ERR", "CMD_ERR", "SIRET_ERR", "CODE_ROUTAGE_ERR",
		"REF_CT_ABSENT", "REF_ERR",
	],
	"refused": [  # 210
		"TX_TVA_ERR", "MONTANTTOTAL_ERR", "CALCUL_ERR", "NON_CONFORME", "DOUBLON",
		"DEST_ERR", "TRANSAC_INC", "EMMET_INC", "CONTRAT_TERM", "DOUBLE_FACT",
		"CMD_ERR", "ADR_ERR", "REF_CT_ABSENT",
	],
}


def reason_codes(status: str) -> list[str]:
	"""Return the allowed MDT-113 reason codes for a status (empty if none required)."""
	return REASON_CODES.get(status, [])


def reason_required(status: str) -> bool:
	"""True if the status requires a reason code (MDT-113)."""
	return bool(STATUSES.get(status, {}).get("detail_required"))


# Reverse lookups built once at import time.
_BY_SUPERPDP: dict[str, str] = {
    v["superpdp"]: k for k, v in STATUSES.items() if v.get("superpdp")
}
_BY_MDT105: dict[str, str] = {v["mdt105"]: k for k, v in STATUSES.items()}


def label(status: str) -> str:
    """Return the human-readable label for a canonical status."""
    return LABELS.get(status, status)


def is_warning(status: str) -> bool:
    """True if an incoming event with this status warrants user attention."""
    return bool(STATUSES.get(status, {}).get("warning"))


def manual_statuses(side: str) -> list[str]:
    """Canonical statuses a user can send manually for the given side.

    ``side`` is "purchase" (we received the invoice, we are the buyer) or
    "sale" (we issued the invoice, we are the seller).
    """
    return [k for k, v in STATUSES.items() if v.get("side") == side]


def to_superpdp_code(status: str) -> str:
    """Translate a canonical status to a SuperPDP ``fr:`` event code."""
    code = STATUSES.get(status, {}).get("superpdp")
    if not code:
        from frappe import throw
        throw(_("The lifecycle status '{0}' is not yet supported by SuperPDP.").format(label(status)))
    return code


def from_superpdp_code(code: str) -> str | None:
    """Translate a SuperPDP ``fr:`` event code back to a canonical status."""
    return _BY_SUPERPDP.get(code)


def to_cdar_codes(status: str) -> tuple[str, str | None]:
    """Return ``(MDT-105, MDT-88)`` codes for a canonical status."""
    vals = STATUSES.get(status)
    if not vals:
        from frappe import throw
        throw(_("Unknown lifecycle status '{0}'.").format(status))
    return vals["mdt105"], vals.get("mdt88")


def from_cdar_code(mdt105: str) -> str | None:
    """Translate a CDAR MDT-105 status code back to a canonical status."""
    return _BY_MDT105.get(str(mdt105))


def side_of(status: str) -> str | None:
	"""The axis a status belongs to: "purchase", "sale", or ``None`` for ``cancelled``.

	The axis is a property of the *status*, never of the invoice direction or of who
	sent the event: on an outgoing invoice the buyer's ``refused`` is still a
	purchase-axis status, and our own ``payment_received`` a sale-axis one. That is
	what lets the two axes advance independently on a single eInvoice.
	"""
	return STATUSES.get(status, {}).get("side")


def is_repeatable(status: str) -> bool:
	"""True if reporting the same status twice in a row is legitimate.

	Partial payments and successive disputes/suspensions each carry new data (an
	amount, a fresh reason code), so they may repeat. ``in_hand``, ``approved``,
	``completed``, ``refused`` and ``cancelled`` are one-shot facts.
	"""
	return bool(STATUSES.get(status, {}).get("repeatable"))


def confirm_required(status: str) -> bool:
	"""True if the UI must ask for confirmation before reporting this status."""
	return bool(STATUSES.get(status, {}).get("confirm_required"))


def confirm_message(status: str) -> str | None:
	"""The confirmation prompt for an irreversible status, if it has a specific one."""
	return CONFIRM_MESSAGES.get(status)


# -----------------------------------------------------------------------------
# Allowed transitions
# -----------------------------------------------------------------------------
# Regulatory end states. A refusal (MDT-105 210) is definitive and a cancellation
# (220) retires the invoice, so neither can be followed by another status.
TERMINAL: frozenset[str] = frozenset({"refused", "cancelled"})

# Allowed successors of a status, within its own axis. Self-edges are implied by
# ``repeatable`` rather than listed here (see :func:`allowed_next`).
#
# The graph is deliberately permissive: on the purchase axis every "decision"
# status can be revisited, because those are real business paths — the auto-send
# reports ``approved`` when the Purchase Invoice is submitted, i.e. often before a
# human has actually checked the invoice, so ``approved -> refused`` and
# ``approved -> dispute`` must stay open. Only four edges are missing, on purpose:
#
#   refused -> *          a refusal is final (only ``cancelled`` may follow, and it
#                         is exempted globally in :func:`transition_error`)
#   cancelled -> *        the invoice no longer exists
#   * -> in_hand          "received" cannot happen a second time
#   payment_sent -> refused   you cannot refuse an invoice you have paid; ``dispute``
#                             remains available as the real remedy
TRANSITIONS: dict[str, frozenset[str]] = {
	# purchase axis: the buyer's handling of an invoice it received
	"in_hand": frozenset(
		{"approved", "partially_approved", "dispute", "suspended", "refused", "payment_sent"}
	),
	"approved": frozenset(
		{"partially_approved", "dispute", "suspended", "refused", "payment_sent"}
	),
	"partially_approved": frozenset(
		{"approved", "dispute", "suspended", "refused", "payment_sent"}
	),
	"dispute": frozenset(
		{"approved", "partially_approved", "suspended", "refused", "payment_sent"}
	),
	"suspended": frozenset(
		{"approved", "partially_approved", "dispute", "refused", "payment_sent"}
	),
	"payment_sent": frozenset({"approved", "partially_approved", "dispute", "suspended"}),
	"refused": frozenset(),
	# sale axis: the seller's own reporting on an invoice it issued
	"completed": frozenset({"payment_received"}),
	"payment_received": frozenset({"completed"}),
	# global
	"cancelled": frozenset(),
}

# What may be reported on an axis that carries no event yet. Derived from ``side``
# so it cannot drift from STATUSES: nothing forces ``in_hand`` to come first, since
# an invoice can perfectly well be approved without its receipt ever being reported.
INITIAL: dict[str, frozenset[str]] = {
	"purchase": frozenset(manual_statuses("purchase")),
	"sale": frozenset(manual_statuses("sale")),
}


def allowed_next(current: str | None, side: str) -> set[str]:
	"""Statuses reportable on ``side`` given its current status.

	``current`` is ``None`` when no event has been recorded on that axis yet.
	"""
	if current is None:
		return set(INITIAL.get(side, ()))
	nxt = set(TRANSITIONS.get(current, ()))
	if is_repeatable(current):
		nxt.add(current)
	return nxt


def transition_error(state: dict, status: str) -> str | None:
	"""Why ``status`` cannot be reported for an invoice in ``state``, or ``None``.

	``state`` is the plain dict returned by
	``etransactions.etransactions.doctype.einvoice_event.einvoice_event.current_lifecycle_state``:
	the current status of each axis plus the ``cancelled`` / ``refused`` flags. Taking
	it as an argument keeps this module free of any database access while still owning
	the whole policy — there is exactly one place to change a rule.
	"""
	if status not in STATUSES:
		return _("Unknown lifecycle status '{0}'.").format(status)

	if state.get("cancelled"):
		return _(
			"This invoice was cancelled on the accredited platform:"
			" no further lifecycle status can be reported."
		)

	if state.get("refused") and status != "cancelled":
		return _(
			"This invoice was refused on the accredited platform and the refusal is"
			" definitive: only '{0}' can still be reported."
		).format(label("cancelled"))

	# 'Cancelled' belongs to no axis and stays reachable from any state (a refused
	# invoice must remain cancellable, otherwise the guided cancellation flow would
	# leave the document stuck).
	if status == "cancelled":
		return None

	side = side_of(status)
	current = state.get(side)

	if current == status:
		if is_repeatable(status):
			return None
		return _("The status '{0}' has already been reported for this invoice.").format(
			label(status)
		)

	if status not in allowed_next(current, side):
		if current:
			return _("The status '{0}' cannot be reported after '{1}'.").format(
				label(status), label(current)
			)
		return _("The status '{0}' cannot be reported at this stage.").format(label(status))

	return None
