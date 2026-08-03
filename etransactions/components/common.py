"""Helpers shared by the platform client components."""

from datetime import datetime

import frappe
from frappe import _


def is_auth_error(status_code: int, message: str) -> bool:
    """True when a platform response signals rejected client credentials.

    Covers HTTP 401 and the OAuth2 ``invalid_client`` / ``invalid_grant`` error
    codes returned by the token endpoint. HUBTIMIZE answers its ``/v1/token`` with
    **400** and ``"Invalid credentials: …"`` rather than a 401, so that wording is
    matched on its own — without it a wrong-environment credential surfaces as a raw
    "Esalink API error 400" instead of the actionable guidance below.
    """
    low = (message or "").lower()
    return (
        status_code == 401
        or "invalid_client" in low
        or "invalid_grant" in low
        or "invalid credentials" in low
    )


def throw_credentials_rejected(message: str) -> None:
    """Raise a shared, actionable error when a platform rejects its credentials.

    Used by every PA client so the cryptic ``invalid_client`` / HTTP 401 surfaces
    the same operator-facing guidance regardless of platform type.
    """
    frappe.throw(
        _(
            "The e-invoicing platform rejected the stored credentials "
            "(authentication failed: {0}). To fix this: <br>"
            "1. Check the platform's <b>Client ID</b> and <b>Client Secret</b> in "
            "<a href='/desk/etransactions-accredited-platform'>eTransactions Accredited Platform</a>.<br>"
            "2. Make sure they match the platform environment — sandbox credentials must use the "
            "sandbox <b>API Base URL</b>, production credentials the production one.<br>"
            "3. For interactive platforms (authorization code), the onboarding may have expired — "
            "re-run the onboarding to obtain a fresh refresh token."
        ).format(message),
        frappe.ValidationError,
        title=_("Platform credentials rejected"),
    )


def to_db_datetime(value: str | None) -> str | None:
    """Normalize a platform ISO-8601 timestamp into a DB-safe datetime string.

    Platforms return UTC timestamps like ``2026-06-23T20:02:28.826685Z``; MySQL's
    DATETIME columns reject the ``T``/``Z`` form, so convert to a naive datetime in
    the site's timezone (``YYYY-MM-DD HH:MM:SS.ffffff``).
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return value
    if dt.tzinfo is not None:
        import pytz
        from frappe.utils import get_system_timezone

        dt = dt.astimezone(pytz.timezone(get_system_timezone())).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def to_utc_iso(dt: datetime | None) -> str | None:
    """Convert a (naive site-timezone) datetime to a UTC ISO-8601 ``Z`` string."""
    if not dt:
        return None
    import pytz
    from frappe.utils import get_system_timezone

    if dt.tzinfo is None:
        dt = pytz.timezone(get_system_timezone()).localize(dt)
    return dt.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
