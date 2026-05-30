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
from .fault_catalog import family_for_code, family_label
from .fdd_results import fdd_issues
from .model_health import model_health_summary
from .model_service import ModelService
from .stack_health import stack_health

# ok -> green, warning -> yellow, critical -> red
TRAFFIC = {"ok": "green", "warning": "yellow", "critical": "red"}


def _stack_issues(stack: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for svc in stack.get("services", []):
        if not isinstance(svc, dict):
            continue
        st = str(svc.get("status") or "")
        if st in {"red", "yellow"}:
            issues.append(
                {
                    "id": f"stack-{svc.get('id')}",
                    "severity": "critical" if st == "red" else "warning",
                    "title": f"{svc.get('label', 'Service')} {st}",
                    "detail": str(svc.get("detail") or ""),
                    "source": "system",
                    "code": "BLD-04" if st == "red" else "",
                    "equipment_family": "BUILDING",
                }
            )
    return issues


def collect_status() -> dict[str, Any]:
    model = ModelService().load()
    health = model_health_summary(model)
    stored = load_alerts()
    merged = merge_auto_issues(model_issues=health.get("issues", []), stored=stored)
    stack = stack_health()
    stack_issues = _stack_issues(stack)
    fdd_alerts = fdd_issues()

    all_alerts = merged["alerts"] + fdd_alerts + stack_issues
    status = merged["status"]
    extra = fdd_alerts + stack_issues
    if extra and status == "ok":
        status = "warning"
    if any(a.get("severity") == "critical" for a in extra):
        status = "critical"

    return {
        "status": status,
        "traffic": TRAFFIC.get(status, "green"),
        "alerts": all_alerts,
        "model_health": health,
        "stack": stack,
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


def faults_by_family() -> dict[str, Any]:
    """Group active alerts into an equipment tree for the dashboard."""
    status = collect_status()
    buckets: dict[str, list[dict[str, Any]]] = {}
    for alert in status["alerts"]:
        if not isinstance(alert, dict):
            continue
        buckets.setdefault(_family_of(alert), []).append(alert)

    families: list[dict[str, Any]] = []
    for family, alerts in sorted(buckets.items()):
        severities = [str(a.get("severity") or "info") for a in alerts]
        families.append(
            {
                "family": family,
                "label": "General / system" if family == "GENERAL" else family_label(family),
                "worst": _worst(severities),
                "traffic": TRAFFIC.get(
                    "critical" if _worst(severities) == "critical"
                    else "warning" if _worst(severities) == "warning"
                    else "ok",
                    "green",
                ),
                "count": len(alerts),
                "faults": alerts,
            }
        )
    return {
        "status": status["status"],
        "traffic": status["traffic"],
        "check_engine": status["status"] != "ok",
        "alert_count": len(status["alerts"]),
        "families": families,
    }
