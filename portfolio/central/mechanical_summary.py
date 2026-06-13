"""Mechanical summary from Edge model queries (read-only)."""

from __future__ import annotations

from typing import Any

from portfolio.central.edge_registry import resolve_site_config, resolve_token
from portfolio.collector.edge_client import EdgeClient


def build_mechanical_summary(site_id: str, *, hours: int = 24) -> dict[str, Any]:
    site = resolve_site_config(site_id)
    client = EdgeClient(site.base_url)
    token = resolve_token(site)
    warnings: list[str] = []

    tree = client.get_model_tree(token=token)
    model_health = client.get_model_health(token=token)
    faults = client.get_faults_status(token=token)
    analytics = client.get_analytics_overview(token=token)
    bacnet = client.try_api_get("/api/bacnet/poll/status", token=token) or {}
    if not analytics:
        warnings.append(
            "Edge /api/analytics/overview not available — upgrade Edge image or using fault status only."
        )

    equipment = tree.get("equipment") if isinstance(tree.get("equipment"), list) else []
    by_type: dict[str, int] = {}
    ahus: list[str] = []
    vavs: list[str] = []
    rtus: list[str] = []
    for eq in equipment:
        if not isinstance(eq, dict):
            continue
        etype = str(eq.get("type") or eq.get("equipment_type") or "unknown").upper()
        by_type[etype] = by_type.get(etype, 0) + 1
        name = str(eq.get("name") or eq.get("id") or "")
        if "AHU" in etype and name:
            ahus.append(name)
        elif "VAV" in etype and name:
            vavs.append(name)
        elif "RTU" in etype and name:
            rtus.append(name)

    counts = model_health.get("counts") if isinstance(model_health.get("counts"), dict) else {}
    issues = model_health.get("issues") if isinstance(model_health.get("issues"), list) else []
    kpis = analytics.get("kpis") if isinstance(analytics.get("kpis"), dict) else {}

    if not equipment:
        warnings.append("Edge model tree returned no equipment — check BRICK model import.")

    readiness = 100
    if issues:
        readiness = max(0, 100 - min(len(issues) * 5, 60))
    if not kpis.get("active_faults") and faults.get("traffic") not in ("green", None):
        readiness = min(readiness, 70)

    return {
        "site_id": site_id,
        "site_name": site.name,
        "base_url": site.base_url,
        "equipment_counts": by_type,
        "ahus": sorted(ahus)[:50],
        "vavs": sorted(vavs)[:100],
        "rtus": sorted(rtus)[:50],
        "point_count": counts.get("points"),
        "equipment_count": counts.get("equipment"),
        "model_warnings": len(issues),
        "model_issues": issues[:20],
        "active_faults": kpis.get("active_faults") or faults.get("alert_count"),
        "total_fault_hours": kpis.get("total_fault_hours"),
        "bacnet_poll": {
            "enabled_points": bacnet.get("enabled_points"),
            "last_poll_at": bacnet.get("last_poll_at"),
        },
        "traffic": faults.get("traffic"),
        "data_readiness_score": readiness,
        "warnings": warnings,
        "lookback_hours": hours,
    }
