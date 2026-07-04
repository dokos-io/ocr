"""Helpers shared by the platform client components."""

from datetime import datetime


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
