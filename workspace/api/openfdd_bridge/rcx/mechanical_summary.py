"""Mechanical summary from local model + analytics (read-only)."""

from __future__ import annotations

from typing import Any

from ..dashboard_analytics import build_model_health, build_overview
from ..model_service import ModelService
from ..model_sparql import query_model_tree
from ..site_defaults import default_site_id, ensure_default_site
from ..ttl_service import TtlService


def _resolve_site_id(site_id: str) -> str:
    sid = str(site_id or "").strip()
    if sid:
        return sid
    svc = ModelService()
    return ensure_default_site(svc, TtlService()) or default_site_id()


def _site_name(site_id: str) -> str:
    try:
        model = ModelService().load()
        for site in model.get("sites") or []:
            if isinstance(site, dict) and str(site.get("id") or "") == site_id:
                name = str(site.get("name") or "").strip()
                if name:
                    return name
        meta = model.get("meta") if isinstance(model.get("meta"), dict) else {}
        name = str(meta.get("site_name") or meta.get("name") or "").strip()
        if name:
            return name
    except Exception:
        pass
    return site_id


def build_mechanical_summary(site_id: str, *, hours: int = 24) -> dict[str, Any]:
    sid = _resolve_site_id(site_id)
    warnings: list[str] = []

    try:
        tree = query_model_tree()
    except Exception as exc:
        tree = {}
        warnings.append(f"Model tree unavailable: {exc}"[:200])

    model_health = build_model_health()
    overview = build_overview(site_id=sid)
    faults_status: dict[str, Any] = {}
    try:
        from ..building_status import collect_status

        status = collect_status()
        faults_status = {
            "traffic": status.get("traffic"),
            "alert_count": len([a for a in status.get("alerts", []) if str(a.get("source")) == "fdd"]),
        }
    except Exception:
        pass

    bacnet: dict[str, Any] = {}
    try:
        from ..poll_throughput import compute_poll_throughput

        pt = compute_poll_throughput(window_minutes=60)
        bacnet = {
            "enabled_points": pt.get("enabled_points"),
            "last_poll_at": pt.get("last_poll_at"),
        }
    except Exception:
        pass

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
    kpis = overview.get("kpis") if isinstance(overview.get("kpis"), dict) else {}

    if not equipment:
        warnings.append("Model tree returned no equipment — check BRICK model import.")

    readiness = 100
    if issues:
        readiness = max(0, 100 - min(len(issues) * 5, 60))
    if not kpis.get("active_faults") and faults_status.get("traffic") not in ("green", None):
        readiness = min(readiness, 70)

    return {
        "site_id": sid,
        "site_name": _site_name(sid),
        "equipment_counts": by_type,
        "ahus": sorted(ahus)[:50],
        "vavs": sorted(vavs)[:100],
        "rtus": sorted(rtus)[:50],
        "point_count": counts.get("points"),
        "equipment_count": counts.get("equipment"),
        "model_warnings": len(issues),
        "model_issues": issues[:20],
        "active_faults": kpis.get("active_faults") or faults_status.get("alert_count"),
        "total_fault_hours": kpis.get("total_fault_hours"),
        "bacnet_poll": {
            "enabled_points": bacnet.get("enabled_points"),
            "last_poll_at": bacnet.get("last_poll_at"),
        },
        "traffic": faults_status.get("traffic"),
        "data_readiness_score": readiness,
        "warnings": warnings,
        "lookback_hours": hours,
        "model_health": model_health,
    }
