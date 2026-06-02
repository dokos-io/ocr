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
        "side": "purchase", "detail_required": True, "decoration": "warning",
    },
    "dispute": {
        "mdt105": "207", "mdt88": "46", "superpdp": "fr:207",
        "side": "purchase", "detail_required": True, "warning": True,
        "decoration": "warning",
    },
    "suspended": {
        "mdt105": "208", "mdt88": "39", "superpdp": None,
        "side": "purchase", "detail_required": True, "warning": True,
        "decoration": "warning",
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
        "side": "purchase", "decoration": "success",
    },
    "payment_received": {
        "mdt105": "212", "mdt88": "47", "superpdp": None,
        "side": "sale", "decoration": "success",
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
