"""BAS-style latched alarms — faults stay active until an operator clears them."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import fault_alarm_latch_path


def _default_doc() -> dict[str, Any]:
    return {"version": 1, "updated_at": None, "alarms": {}}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_latch() -> dict[str, Any]:
    path = fault_alarm_latch_path()
    if not path.is_file():
        return _default_doc()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_doc()
    if not isinstance(raw, dict):
        return _default_doc()
    alarms = raw.get("alarms")
    if not isinstance(alarms, dict):
        raw["alarms"] = {}
    return raw


def save_latch(doc: dict[str, Any]) -> None:
    path = fault_alarm_latch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["updated_at"] = _now_iso()
    payload = json.dumps(doc, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, mode="w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def stable_alert_id(alert: dict[str, Any]) -> str:
    explicit = str(alert.get("id") or "").strip()
    if explicit:
        return explicit
    source = str(alert.get("source") or "alert")
    title = str(alert.get("title") or "")
    detail = str(alert.get("detail") or "")[:120]
    return f"{source}:{title}:{detail}"


def apply_alarm_latch(live_alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge live alerts into a latched store; return active (uncleared) alarms."""
    doc = load_latch()
    alarms: dict[str, Any] = doc.setdefault("alarms", {})
    now = _now_iso()
    live_by_id: dict[str, dict[str, Any]] = {}
    for alert in live_alerts:
        if not isinstance(alert, dict):
            continue
        aid = stable_alert_id(alert)
        live_by_id[aid] = alert

    for aid, alert in live_by_id.items():
        entry = alarms.get(aid)
        if entry is None:
            alarms[aid] = {"first_seen": now, "last_seen": now, "alert": alert}
            continue
        entry["last_seen"] = now
        entry["alert"] = alert
        if entry.get("cleared_at"):
            entry.pop("cleared_at", None)
            entry.pop("cleared_by", None)

    active: list[dict[str, Any]] = []
    for aid, entry in alarms.items():
        if entry.get("cleared_at"):
            continue
        alert = live_by_id.get(aid) or entry.get("alert")
        if isinstance(alert, dict):
            active.append(alert)

    save_latch(doc)
    return active


def clear_alarms(alert_ids: list[str], *, cleared_by: str) -> dict[str, Any]:
    doc = load_latch()
    alarms: dict[str, Any] = doc.setdefault("alarms", {})
    now = _now_iso()
    cleared: list[str] = []
    for raw_id in alert_ids:
        aid = str(raw_id or "").strip()
        if not aid:
            continue
        entry = alarms.get(aid)
        if entry is None:
            entry = {
                "first_seen": now,
                "last_seen": now,
                "alert": {"id": aid, "title": "Cleared alarm", "source": "operator"},
            }
            alarms[aid] = entry
        entry["cleared_at"] = now
        entry["cleared_by"] = cleared_by
        cleared.append(aid)
    save_latch(doc)
    return {"cleared": cleared, "count": len(cleared)}
