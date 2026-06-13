"""Display timestamps in the analyst's local timezone."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

_DEFAULT_TZ = os.environ.get("OPENFDD_DISPLAY_TZ", "").strip()


def display_tz() -> ZoneInfo:
    if _DEFAULT_TZ:
        try:
            return ZoneInfo(_DEFAULT_TZ)
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")  # type: ignore[arg-type]


def tz_label() -> str:
    tz = display_tz()
    now = datetime.now(tz)
    return now.tzname() or str(tz)


def format_ts_local(value: object | None) -> str:
    """Format ISO or pandas timestamp for display in local TZ."""
    if value is None or (isinstance(value, float) and value != value):
        return "—"
    text = str(value).strip()
    if not text or text.lower() in {"nat", "none"}:
        return "—"
    try:
        ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:19]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    local = ts.astimezone(display_tz())
    return local.strftime("%Y-%m-%d %H:%M:%S")
