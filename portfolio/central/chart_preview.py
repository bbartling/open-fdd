"""Matplotlib chart previews with fault overlays (BytesIO → base64)."""

from __future__ import annotations

import base64
import io
from datetime import datetime, timedelta, timezone
from typing import Any

from portfolio.central.chart_specs import CHART_SPECS, SECTION_SPECS, chart_readiness
from portfolio.central.edge_registry import resolve_site_config, resolve_token
from portfolio.central.mechanical_summary import build_mechanical_summary
from portfolio.central.trend_charts import (
    columns_for_roles,
    overlays_from_readings,
    render_trend_ax,
)
from portfolio.collector.edge_client import EdgeClient

TREND_CHARTS = {
    "ahu_sat_vs_setpoint": ["supply_air_temperature", "supply_air_temperature_setpoint"],
    "ahu_duct_static_vs_setpoint": ["duct_static_pressure", "duct_static_pressure_setpoint"],
    "vav_zone_temp": ["zone_temperature", "zone_cooling_setpoint", "zone_heating_setpoint"],
}

SEVERITY_COLORS = {
    "critical": (0.86, 0.15, 0.15, 0.25),
    "warning": (0.96, 0.62, 0.04, 0.22),
    "high": (0.95, 0.45, 0.1, 0.22),
    "medium": (0.98, 0.75, 0.15, 0.18),
    "info": (0.4, 0.5, 0.7, 0.15),
}


def _window(hours: int) -> tuple[str, str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    return start.isoformat(), end.isoformat()


def _png_base64(title: str, render_fn) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    render_fn(ax)
    ax.set_title(title, fontsize=11)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _fault_overlays(ax, overlays: list[dict[str, Any]]) -> None:
    for ov in overlays:
        color = SEVERITY_COLORS.get(str(ov.get("severity") or "warning").lower(), SEVERITY_COLORS["warning"])
        ax.axvspan(float(ov.get("x0", 0)), float(ov.get("x1", 1)), color=color, label=ov.get("label"))


def build_rcx_preview(
    *,
    site_id: str,
    hours: int = 24,
    chart_ids: list[str] | None = None,
    show_fault_overlays: bool = True,
) -> dict[str, Any]:
    start, end = _window(hours)
    mech = build_mechanical_summary(site_id, hours=hours)
    site = resolve_site_config(site_id)
    client = EdgeClient(site.base_url)
    token = resolve_token(site)
    analytics = client.get_analytics_overview(token=token)
    faults_data = client.get_analytics_faults(hours=hours, token=token)

    roles_present: set[str] = set()
    tree = client.get_model_tree(token=token)
    for pt in tree.get("points") or []:
        if isinstance(pt, dict):
            role = str(pt.get("brick_type") or pt.get("role") or "").strip()
            if role:
                roles_present.add(role)

    fault_rows = faults_data.get("faults") if isinstance(faults_data.get("faults"), list) else []
    has_faults = bool(fault_rows)
    trend_cache: dict[str, dict[str, Any]] = {}

    def _readings_for_chart(chart_id: str) -> dict[str, Any]:
        if chart_id in trend_cache:
            return trend_cache[chart_id]
        roles = TREND_CHARTS.get(chart_id)
        if not roles:
            trend_cache[chart_id] = {}
            return {}
        cols = columns_for_roles(tree, roles)
        if not cols:
            trend_cache[chart_id] = {}
            return {}
        try:
            data = client.get_timeseries_readings(
                site_id,
                cols,
                hours=hours,
                token=token,
                include_faults=show_fault_overlays,
            )
        except RuntimeError:
            data = {}
        trend_cache[chart_id] = data
        return data

    has_trends = any((_readings_for_chart(cid).get("row_count") or 0) > 0 for cid in TREND_CHARTS)

    available: list[dict[str, Any]] = []
    disabled: list[dict[str, Any]] = []
    previews: list[dict[str, Any]] = []

    for spec in CHART_SPECS:
        if chart_ids and spec["chart_id"] not in chart_ids:
            continue
        cid = spec["chart_id"]
        trend_ok = (_readings_for_chart(cid).get("row_count") or 0) > 0 if cid in TREND_CHARTS else has_trends
        ok, reason = chart_readiness(
            spec,
            roles_present=roles_present,
            has_fault_data=has_faults,
            has_trend_data=trend_ok if cid in TREND_CHARTS else True,
        )
        if ok:
            available.append(spec)
        else:
            disabled.append({**spec, "reason": reason})

    by_sev = analytics.get("faults_by_severity") or []
    if has_faults and (not chart_ids or "fault_hours_by_severity" in (chart_ids or [])):
        labels = [r.get("group", "") for r in by_sev]
        values = [float(r.get("elapsed_hours") or 0) for r in by_sev]

        def render(ax):
            ax.bar(labels, values, color="#2563eb")
            ax.set_ylabel("Hours (est.)")

        previews.append(
            {
                "chart_id": "fault_hours_by_severity",
                "title": "Fault hours by severity",
                "image_base64": _png_base64("Fault hours by severity", render),
                "warnings": [],
            }
        )

    by_eq = analytics.get("fault_hours_by_equipment") or []
    if has_faults and (not chart_ids or "fault_hours_by_equipment" in (chart_ids or [])):
        labels = [str(r.get("group", ""))[:20] for r in by_eq[:12]]
        values = [float(r.get("elapsed_hours") or 0) for r in by_eq[:12]]

        def render_eq(ax):
            ax.bar(labels, values, color="#2563eb")
            ax.tick_params(axis="x", rotation=45, labelsize=7)
            ax.set_ylabel("Hours (est.)")

        previews.append(
            {
                "chart_id": "fault_hours_by_equipment",
                "title": "Fault hours by equipment",
                "image_base64": _png_base64("Fault hours by equipment", render_eq),
                "warnings": [],
            }
        )

    for chart_id, roles in TREND_CHARTS.items():
        if chart_ids and chart_id not in chart_ids:
            continue
        if chart_id not in [p["chart_id"] for p in previews] and chart_id in [s["chart_id"] for s in available]:
            readings = _readings_for_chart(chart_id)
            if (readings.get("row_count") or 0) <= 0:
                continue
            title = next((s["title"] for s in CHART_SPECS if s["chart_id"] == chart_id), chart_id)
            overlays = overlays_from_readings(readings, show=show_fault_overlays)

            def _make_render(rd, ov, rl):
                def render(ax):
                    render_trend_ax(ax, rd, title_cols=rl, overlays=ov, overlay_fn=_fault_overlays)

                return render

            previews.append(
                {
                    "chart_id": chart_id,
                    "title": title,
                    "image_base64": _png_base64(title, _make_render(readings, overlays, roles)),
                    "warnings": [],
                }
            )

    fault_overlays: list[dict[str, Any]] = []
    if show_fault_overlays:
        for chart_id in TREND_CHARTS:
            rd = _readings_for_chart(chart_id)
            fault_overlays.extend(overlays_from_readings(rd, show=True)[:8])

    return {
        "site_id": site_id,
        "site_name": site.name,
        "window": {"start": start, "end": end, "hours": hours},
        "mechanical_summary": mech,
        "available_charts": available,
        "disabled_charts": disabled,
        "sections": SECTION_SPECS,
        "fault_summary": {
            "active_faults": len(fault_rows),
            "total_fault_hours": (analytics.get("kpis") or {}).get("total_fault_hours"),
        },
        "fault_rows": fault_rows[:50],
        "fault_overlays": fault_overlays,
        "chart_previews": previews,
        "warnings": mech.get("warnings") or [],
        "missing_roles": [
            str(i.get("title") or "") for i in (mech.get("model_issues") or [])[:10]
        ],
    }


def generate_rcx_docx(
    *,
    site_id: str,
    hours: int = 24,
    sections: list[str] | None = None,
    charts: list[str] | None = None,
) -> tuple[bytes, str]:
    preview = build_rcx_preview(site_id=site_id, hours=hours, chart_ids=charts)
    site = resolve_site_config(site_id)
    fault_rows = preview.get("fault_rows") or []

    try:
        from open_fdd.reports.rcx_docx import build_rcx_docx
    except ImportError:
        from portfolio.central.rcx_report import build_rcx_docx as legacy_build

        blob = legacy_build(
            site_id=site_id,
            site_name=site.name,
            validation=None,
            rollups=[],
            warnings=preview.get("warnings"),
        )
        fname = f"openfdd-rcx-{site_id}.docx"
        return blob, fname

    overview = {
        "active_faults": preview["fault_summary"]["active_faults"],
        "total_fault_hours": preview["fault_summary"]["total_fault_hours"],
        "missing_roles": preview.get("missing_roles"),
    }
    if preview.get("mechanical_summary"):
        overview["mechanical_summary"] = preview["mechanical_summary"]

    blob = build_rcx_docx(
        site_id=site_id,
        site_name=site.name,
        window=preview.get("window") or {},
        fault_rows=fault_rows,
        overview=overview,
        sections=sections,
        charts=charts,
        warnings=preview.get("warnings"),
    )
    start = (preview.get("window") or {}).get("start", "")[:10]
    end = (preview.get("window") or {}).get("end", "")[:10]
    fname = f"openfdd-rcx-{site_id}-{start}-{end}.docx"
    return blob, fname
