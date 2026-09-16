"""PPF e-reporting status registry and mappings.

Alongside B2B e-invoicing, the French reform requires **e-reporting**: B2C sales,
sales to foreign/non-established parties, and payment data for services are
aggregated by the accredited platform and declared to the public portal (PPF).
The platform reports the fate of each declaration through ``ppf:ereporting*``
status events.

This mirrors :mod:`etransactions.plateforme_agreee.lifecycle_status`: a single
canonical *state* string is used by higher-level code, and the wire status codes
are translated here. Only SuperPDP exposes e-reporting today (see
``PLATFORM_CAPABILITIES`` in :mod:`etransactions.plateforme_agreee.session`).
"""

from frappe import _lt


# wire status_code -> definition
#   state    : internal state (sent | acknowledged | rejected | done | error)
#   warning  : the declaration needs user attention (rejected / errored)
#   weight   : ordering used to pick the most advanced/severe event in a list
STATUSES: dict[str, dict] = {
	"ppf:ereporting": {"state": "sent", "weight": 1},
	"ppf:ereporting-ack": {"state": "acknowledged", "weight": 2},
	"ppf:ereporting-response-ok": {"state": "done", "weight": 5},
	"ppf:ereporting-ack-error": {"state": "error", "warning": True, "weight": 3},
	"ppf:ereporting-rejected": {"state": "rejected", "warning": True, "weight": 4},
}

# Human-readable labels per internal state, translatable. ``_lt`` because the dict is
# built at import time (see ``lifecycle_status.LABELS``).
STATE_LABELS: dict[str, str] = {
	"sent": _lt("Submitted to PPF"),
	"acknowledged": _lt("Acknowledged"),
	"rejected": _lt("Rejected by PPF"),
	"done": _lt("Accepted by PPF"),
	"error": _lt("Error"),
}


def state_for(status_code: str) -> str:
	"""Translate a ``ppf:ereporting*`` wire code to an internal state."""
	return STATUSES.get(status_code, {}).get("state", "sent")


def is_warning(status_code: str) -> bool:
	"""True if an event with this status code warrants user attention."""
	return bool(STATUSES.get(status_code, {}).get("warning"))


def label(state: str) -> str:
	"""Return the human-readable label for an internal state."""
	return str(STATE_LABELS.get(state, state))


def derive_state(status_codes: list[str]) -> str:
	"""Pick the most advanced/severe state from a declaration's event codes.

	An accepted response (``-response-ok``) outranks a rejection, which outranks
	an ack-error, which outranks a plain ack, which outranks the initial submit —
	matching the ``weight`` ordering above.
	"""
	if not status_codes:
		return "sent"
	best_code = max(
		status_codes,
		key=lambda c: STATUSES.get(c, {}).get("weight", 0),
	)
	return state_for(best_code)
