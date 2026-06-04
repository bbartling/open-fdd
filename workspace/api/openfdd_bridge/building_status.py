"""Single source of truth for the building check-engine status.

Merges model-health issues, scheduled FDD fault results, persisted (agent/operator)
alerts, and live stack health into one alert list + traffic state. Both
``building_routes`` (the headline card) and ``faults_routes`` (the equipment
fault tree) build their responses from :func:`collect_status` so they never
disagree.
"""

from __future__ import annotations

from typing import Any

from .building_alerts import load_alerts, merge_auto_issues
from .device_poll_health import get_device_poll_snapshot, poll_health_alerts
from .fault_catalog import family_for_code, family_label
from .fdd_results import fdd_issues
from .model_health import model_health_summary
from .model_service import ModelService
from .stack_health import stack_health

# ok -> green, warning -> yellow, critical -> red
TRAFFIC = {"ok": "green", "warning": "yellow", "critical": "red"}


def collect_status() -> dict[str, Any]:
    model = ModelService().load()
    health = model_health_summary(model)
    model_issues = health.get("issues", []) if health.get("configured") else []
    stored = load_alerts()
    merged = merge_auto_issues(model_issues=model_issues, stored=stored)
    fdd_alerts = fdd_issues()
    try:
        poll_snap = get_device_poll_snapshot(force=False)
        poll_alerts = poll_health_alerts(poll_snap)
    except Exception:
        poll_alerts = []

    all_alerts = merged["alerts"] + fdd_alerts + poll_alerts
    status = merged["status"]
    if (fdd_alerts or poll_alerts) and status == "ok":
        status = "warning"
    if any(a.get("severity") == "critical" for a in all_alerts):
        status = "critical"

    return {
        "status": status,
        "traffic": TRAFFIC.get(status, "green"),
        "alerts": all_alerts,
        "model_health": health,
        "model_configured": bool(health.get("configured")),
        "stack": stack_health(),
        "fdd_alert_count": len(fdd_alerts),
    }


def _family_of(alert: dict[str, Any]) -> str:
    explicit = str(alert.get("equipment_family") or "").strip().upper()
    if explicit:
        return explicit
    by_code = family_for_code(alert.get("code"))
    if by_code:
        return by_code
    return "GENERAL"


def _worst(severities: list[str]) -> str:
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    return "info"


def faults_by_family(status: dict[str, Any] | None = None) -> dict[str, Any]:
    """Group active alerts into an equipment tree for the dashboard."""
    if status is None:
        status = collect_status()
    buckets: dict[str, list[dict[str, Any]]] = {}
    for alert in status["alerts"]:
        if not isinstance(alert, dict):
            continue
        buckets.setdefault(_family_of(alert), []).append(alert)

    families: list[dict[str, Any]] = []
    for family, alerts in sorted(buckets.items()):
        severities = [str(a.get("severity") or "info") for a in alerts]
        worst = _worst(severities)
        traffic_key = "critical" if worst == "critical" else "warning" if worst == "warning" else "ok"
        families.append(
            {
                "family": family,
                "label": "General / system" if family == "GENERAL" else family_label(family),
                "worst": worst,
                "traffic": TRAFFIC.get(traffic_key, "green"),
                "count": len(alerts),
                "faults": alerts,
            }
        )
    return {
        "status": status["status"],
        "traffic": status["traffic"],
        "check_engine": status["status"] != "ok",
        "alert_count": len(status["alerts"]),
        "model_configured": status.get("model_configured", False),
        "families": families,
    }


def dashboard_snapshot(*, redacted: bool = False) -> dict[str, Any]:
    """Single payload for dashboard polling / WebSocket push."""
    status = collect_status()
    stack = status["stack"]
    if redacted:
        stack = {
            "ok": stack.get("ok"),
            "overall": stack.get("overall"),
            "services": [
                {
                    "id": s.get("id"),
                    "label": s.get("label"),
                    "status": s.get("status"),
                    "configured": s.get("configured"),
                }
                for s in stack.get("services", [])
                if isinstance(s, dict)
            ],
        }
        faults = {
            "status": status["status"],
            "traffic": status["traffic"],
            "check_engine": status["status"] != "ok",
            "alert_count": len(status.get("alerts", [])),
            "model_configured": bool(status.get("model_configured")),
            "families": [],
        }
    else:
        faults = faults_by_family(status)
    return {"stack": stack, "faults": faults}
