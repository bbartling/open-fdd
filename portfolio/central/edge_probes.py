"""Read-only edge health / fault / model probes for Central validation."""

from __future__ import annotations

from typing import Any

from portfolio.collector.edge_client import api_get, login
from portfolio.collector.collector import SiteConfig


def _fdd_alerts_missing_equipment(faults: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for fam in faults.get("families") or []:
        for alert in fam.get("faults") or []:
            if alert.get("source") != "fdd":
                continue
            ctx = alert.get("model_context") or {}
            eq = ctx.get("equipment") if isinstance(ctx.get("equipment"), dict) else {}
            eq_name = next(
                (
                    s
                    for s in (
                        str(ctx.get("equipment_name") or "").strip(),
                        str(alert.get("equipment_name") or "").strip(),
                        str(eq.get("name") or "").strip(),
                    )
                    if s
                ),
                "",
            )
            if not eq_name:
                missing.append(str(alert.get("code") or alert.get("title") or "fdd-alert"))
    return missing


def validate_edge_readonly(site: SiteConfig, *, timeout: int = 120) -> dict[str, Any]:
    """One-shot read-only validation against an edge Operator Bridge."""
    result: dict[str, Any] = {
        "site_id": site.site_id,
        "base_url": site.base_url,
        "ok": True,
        "checks": {},
        "errors": [],
    }
    try:
        token = login(site.base_url, username=site.username, password=site.password, timeout=timeout)
    except Exception as exc:
        result["ok"] = False
        result["errors"].append(f"login: {exc}")
        return result

    def _probe(name: str, path: str) -> dict[str, Any]:
        try:
            body = api_get(site.base_url, token, path, timeout=timeout)
            return {"ok": True, "path": path, "body": body}
        except Exception as exc:
            result["ok"] = False
            result["errors"].append(f"{name}: {exc}")
            return {"ok": False, "path": path, "error": str(exc)}

    health = _probe("health", "/health")
    result["checks"]["health"] = health
    stack = _probe("stack", "/health/stack")
    result["checks"]["stack"] = stack
    model = _probe("model_health", "/api/model/health")
    result["checks"]["model_health"] = model
    poll = _probe("bacnet_poll", "/api/bacnet/poll/status")
    result["checks"]["bacnet_poll"] = poll
    faults = _probe("faults_status", "/api/faults/status")
    result["checks"]["faults_status"] = faults

    if faults.get("ok"):
        body = faults.get("body") or {}
        missing_eq = _fdd_alerts_missing_equipment(body)
        result["checks"]["fdd_equipment_context"] = {
            "missing_count": len(missing_eq),
            "missing_samples": missing_eq[:10],
        }
        if missing_eq:
            result["ok"] = False
            result["errors"].append(
                f"{len(missing_eq)} FDD alert(s) missing equipment context"
            )
        result["traffic"] = str(body.get("traffic") or "")

    if model.get("ok"):
        counts = (model.get("body") or {}).get("counts") or {}
        dup_pts = int(counts.get("duplicate_point_ids") or 0)
        dup_dev = int(counts.get("duplicate_bacnet_device_instances") or 0)
        if dup_pts or dup_dev:
            result["ok"] = False
            result["errors"].append(f"model duplicates: points={dup_pts} devices={dup_dev}")

    return result
