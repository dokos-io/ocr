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

from frappe import _, _lt


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
#
# ``_lt`` and not ``_``: this dict is built once at import time, so ``_`` would
# freeze every label into whatever language the worker happened to be serving on
# first import and hand that to every later user. The lazy string resolves per
# request instead. The accessors below coerce it back to a real ``str`` — a
# ``_LazyTranslate`` must never escape into a whitelisted return value, since it
# raises on ``__eq__`` and has no ``__json__``.
LABELS: dict[str, str] = {
    "in_hand": _lt("In Hand"),
    "approved": _lt("Approved"),
    "partially_approved": _lt("Partially Approved"),
    "dispute": _lt("Disputed"),
    "suspended": _lt("Suspended"),
    "completed": _lt("Completed"),
    "refused": _lt("Refused"),
    "payment_sent": _lt("Payment Sent"),
    "payment_received": _lt("Payment Received"),
    "cancelled": _lt("Cancelled"),
}

# Extra confirmation prompt for the irreversible statuses (``confirm_required``).
# Kept next to LABELS so the translation tooling picks it up, and served to the
# client so the wording lives in one place instead of being duplicated in JS.
CONFIRM_MESSAGES: dict[str, str] = {
    "refused": _lt(
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

# Human-readable wording for the MDT-113 codes, keyed by *code* rather than by
# status: the four lists above hold 59 entries but only 27 distinct codes (every
# refusal code is also a dispute code), so keying by status would duplicate most
# of them and let the copies drift apart. ``test_every_reason_code_has_a_label``
# guards that every code in REASON_CODES is covered here.
#
# ``_lt`` for the same reason as LABELS above.
REASON_LABELS: dict[str, str] = {
	"ADR_ERR": _lt("Incorrect address"),
	"ART_ERR": _lt("Incorrect item"),
	"AUTRE": _lt("Other"),
	"CALCUL_ERR": _lt("Calculation error"),
	"CMD_ERR": _lt("Incorrect order reference"),
	"CODE_ROUTAGE_ERR": _lt("Incorrect routing code"),
	"CONTRAT_TERM": _lt("Contract ended"),
	"COORD_BANC_ERR": _lt("Incorrect bank details"),
	"DEST_ERR": _lt("Incorrect recipient"),
	"DEST_INC": _lt("Unknown recipient"),
	"DOUBLE_FACT": _lt("Double invoicing"),
	"DOUBLON": _lt("Duplicate"),
	"EMMET_INC": _lt("Unknown issuer"),
	"JUSTIF_ABS": _lt("Missing supporting document"),
	"LIVR_INCOMP": _lt("Incomplete delivery"),
	"MODPAI_ERR": _lt("Incorrect payment method"),
	"MONTANTTOTAL_ERR": _lt("Incorrect total amount"),
	"NON_CONFORME": _lt("Non-compliant invoice"),
	"PU_ERR": _lt("Incorrect unit price"),
	"QTE_ERR": _lt("Incorrect quantity"),
	"QUALITE_ERR": _lt("Quality not as agreed"),
	"REF_CT_ABSENT": _lt("Missing contract reference"),
	"REF_ERR": _lt("Incorrect reference"),
	"REM_ERR": _lt("Incorrect discount"),
	"SIRET_ERR": _lt("Incorrect SIRET"),
	"TRANSAC_INC": _lt("Unknown transaction"),
	"TX_TVA_ERR": _lt("Incorrect VAT rate"),
}

# One sentence per code, shown under the picker so the user does not have to infer
# the difference between, say, "Duplicate" and "Double invoicing".
REASON_DESCRIPTIONS: dict[str, str] = {
	"ADR_ERR": _lt("The billing or postal address on the invoice is wrong."),
	"ART_ERR": _lt("An invoiced item is not the one that was ordered or delivered."),
	"AUTRE": _lt("None of the other reasons applies; explain it in the comment."),
	"CALCUL_ERR": _lt("The totals do not add up from the lines and taxes."),
	"CMD_ERR": _lt("The purchase order referenced on the invoice is wrong or unknown."),
	"CODE_ROUTAGE_ERR": _lt("The routing code does not correspond to the recipient service."),
	"CONTRAT_TERM": _lt("The contract this invoice relies on has already ended."),
	"COORD_BANC_ERR": _lt("The bank details differ from the ones on file for the supplier."),
	"DEST_ERR": _lt("The invoice is addressed to the wrong legal entity or establishment."),
	"DEST_INC": _lt("The recipient identified on the invoice cannot be found."),
	"DOUBLE_FACT": _lt("The same goods or services have already been invoiced separately."),
	"DOUBLON": _lt("This exact invoice has already been received."),
	"EMMET_INC": _lt("The issuer is not a known supplier."),
	"JUSTIF_ABS": _lt("A required supporting document is missing from the invoice."),
	"LIVR_INCOMP": _lt("Part of the invoiced delivery has not been received."),
	"MODPAI_ERR": _lt("The payment method differs from the agreed one."),
	"MONTANTTOTAL_ERR": _lt("The total amount does not match what was agreed."),
	"NON_CONFORME": _lt("The invoice does not meet the legal or contractual requirements."),
	"PU_ERR": _lt("A unit price differs from the order or the price list."),
	"QTE_ERR": _lt("An invoiced quantity differs from the one ordered or received."),
	"QUALITE_ERR": _lt("The goods or services delivered are not of the agreed quality."),
	"REF_CT_ABSENT": _lt("The contract reference required for payment is missing."),
	"REF_ERR": _lt("A reference carried by the invoice is wrong."),
	"REM_ERR": _lt("An agreed discount is missing or miscalculated."),
	"SIRET_ERR": _lt("The SIRET on the invoice is wrong or does not match the recipient."),
	"TRANSAC_INC": _lt("No order or contract matching this invoice can be found."),
	"TX_TVA_ERR": _lt("A VAT rate applied on the invoice is wrong."),
}


def reason_codes(status: str) -> list[str]:
	"""Return the allowed MDT-113 reason codes for a status (empty if none required).

	The bare wire codes, kept as the server-side validator's input. The UI wants
	:func:`reason_code_options` instead.
	"""
	return REASON_CODES.get(status, [])


def reason_label(code: str) -> str:
	"""Human-readable wording for an MDT-113 code, falling back to the code itself."""
	return str(REASON_LABELS.get(code, code))


def reason_description(code: str) -> str:
	"""One-sentence explanation of an MDT-113 code, or an empty string."""
	description = REASON_DESCRIPTIONS.get(code)
	return str(description) if description else ""


def all_reason_labels() -> dict[str, str]:
	"""Every MDT-113 code mapped to its wording, for rendering a stored reason.

	The event history keeps the wire code; the client needs the whole map at once to
	show a past refusal's reason without a lookup per row.
	"""
	return {code: str(text) for code, text in REASON_LABELS.items()}


def reason_code_options(status: str) -> list[dict]:
	"""The MDT-113 codes for a status, ready for a picker.

	Derived from :data:`REASON_CODES` so the offered list can never drift from the
	one the schematron accepts. Labels are coerced to plain ``str`` here: this feeds
	a whitelisted endpoint, and a lazy translation cannot be serialised to JSON.
	"""
	return [
		{
			"value": code,
			"label": reason_label(code),
			"description": reason_description(code),
		}
		for code in reason_codes(status)
	]


def reason_required(status: str) -> bool:
	"""True if the status requires a reason code (MDT-113)."""
	return bool(STATUSES.get(status, {}).get("detail_required"))


# Reverse lookups built once at import time.
_BY_SUPERPDP: dict[str, str] = {
    v["superpdp"]: k for k, v in STATUSES.items() if v.get("superpdp")
}
_BY_MDT105: dict[str, str] = {v["mdt105"]: k for k, v in STATUSES.items()}


def label(status: str) -> str:
    """Return the human-readable label for a canonical status.

    Coerced to ``str``: LABELS holds lazy translations, and callers put the result
    into JSON payloads and message formatting.
    """
    return str(LABELS.get(status, status))


def source_label(status: str) -> str:
    """Return the untranslated (English) label for a canonical status.

    For values persisted to the database: a translated label would be frozen in the
    language of whoever inserted the row (often the scheduler). The English source
    is the translation key, so the desk translates it on display with ``__()``.
    """
    lazy = LABELS.get(status)
    return lazy.msg if lazy is not None else status


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
	message = CONFIRM_MESSAGES.get(status)
	return str(message) if message else None


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
