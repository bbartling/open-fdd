"""Building check-engine alerts — operator-visible issues the AI can update."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .paths import building_alerts_path

_SEVERITIES = frozenset({"info", "warning", "critical"})


def _default_doc() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "updated_by": None,
        "status": "ok",
        "alerts": [],
    }


def load_alerts() -> dict[str, Any]:
    path = building_alerts_path()
    if not path.is_file():
        return _default_doc()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_doc()
    if not isinstance(raw, dict):
        return _default_doc()
    alerts = raw.get("alerts")
    if not isinstance(alerts, list):
        raw["alerts"] = []
    return raw


def save_alerts(doc: dict[str, Any]) -> None:
    path = building_alerts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _derive_status(alerts: list[dict[str, Any]]) -> str:
    if any(str(a.get("severity")) == "critical" for a in alerts):
        return "critical"
    if any(str(a.get("severity")) == "warning" for a in alerts):
        return "warning"
    return "ok"


def replace_alerts(
    alerts: list[dict[str, Any]],
    *,
    updated_by: str,
    status: str | None = None,
) -> dict[str, Any]:
    cleaned: list[dict[str, Any]] = []
    for item in alerts:
        if not isinstance(item, dict):
            continue
        sev = str(item.get("severity") or "info")
        if sev not in _SEVERITIES:
            sev = "info"
        cleaned.append(
            {
                "id": str(item.get("id") or uuid4()),
                "severity": sev,
                "title": str(item.get("title") or "Untitled")[:200],
                "detail": str(item.get("detail") or "")[:2000],
                "source": str(item.get("source") or "agent")[:64],
            }
        )
    doc = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": updated_by,
        "status": status or _derive_status(cleaned),
        "alerts": cleaned,
    }
    save_alerts(doc)
    return doc


def merge_auto_issues(
    *,
    model_issues: list[dict[str, str]],
    stored: dict[str, Any],
) -> dict[str, Any]:
    manual = [
        a
        for a in stored.get("alerts", [])
        if isinstance(a, dict) and str(a.get("source", "")) not in {"model_health", "system"}
    ]
    auto = [
        {
            "id": f"model-{idx}",
            "severity": issue.get("severity", "warning"),
            "title": issue.get("title", ""),
            "detail": issue.get("detail", ""),
            "source": "model_health",
        }
        for idx, issue in enumerate(model_issues)
    ]
    combined = auto + manual
    status = _derive_status(combined)
    if any(i.get("severity") == "critical" for i in model_issues):
        status = "critical"
    elif status == "ok" and model_issues:
        status = "warning"
    return {
        "status": status,
        "alert_count": len(combined),
        "alerts": combined,
        "stored_updated_at": stored.get("updated_at"),
        "stored_updated_by": stored.get("updated_by"),
    }
