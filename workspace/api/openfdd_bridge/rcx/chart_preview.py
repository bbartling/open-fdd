"""RCx chart previews with fault overlays (Plotly → base64 PNG)."""

from __future__ import annotations

import base64
import io
from datetime import datetime, timedelta, timezone
from typing import Any

from ..dashboard_analytics import build_fault_analytics, build_model_health, build_overview
from ..fdd_query_presets import run_fdd_preset
from ..model_service import ModelService
from ..model_sparql import query_model_tree
from ..site_defaults import default_site_id, ensure_default_site
from ..ttl_service import TtlService
from .chart_readings import read_chart_readings_with_plot_fallback
from .chart_specs import (
    CHART_SPECS,
    SECTION_SPECS,
    TREND_CHART_IDS,
    chart_readiness,
    suggest_charts_for_faults,
)
from .mechanical_narrative import build_mechanical_narrative
from .mechanical_summary import build_mechanical_summary
from .plotly_charts import build_bar_figure, build_building_inventory_figure, build_trend_figure
from .report_bundles import (
    build_report_bundles,
    chart_ids_for_bundles,
    equipment_charts_for_ids,
)
from .rcx_narrative import build_chart_narrative
from .rcx_stats import summarize_readings
from .trend_charts import (
    canonical_roles_present,
    columns_for_roles,
    overlays_from_readings,
    resolve_roles_on_tree,
)

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


def _resolve_site(site_id: str) -> tuple[str, str]:
    sid = str(site_id or "").strip()
    if not sid:
        svc = ModelService()
        sid = ensure_default_site(svc, TtlService()) or default_site_id()
    name = sid
    try:
        model = ModelService().load()
        for site in model.get("sites") or []:
            if isinstance(site, dict) and str(site.get("id") or "") == sid:
                name = str(site.get("name") or sid)
                break
        meta = model.get("meta") if isinstance(model.get("meta"), dict) else {}
        if name == sid:
            name = str(meta.get("site_name") or meta.get("name") or sid)
    except Exception:
        pass
    return sid, name


def _window(
    hours: int,
    *,
    start: str | None = None,
    end: str | None = None,
) -> tuple[str, str, int]:
    if start and end:
        try:
            s = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            e = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
            if e > s:
                span_h = max(2, min(8760, int((e - s).total_seconds() // 3600) or hours))
                return s.isoformat(), e.isoformat(), span_h
        except ValueError:
            pass
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(hours=hours)
    return start_dt.isoformat(), end_dt.isoformat(), hours


def _enrich_preview(
    preview: dict[str, Any],
    readings: dict[str, Any],
    *,
    fault_summary: dict[str, Any],
) -> dict[str, Any]:
    stats = summarize_readings(
        readings,
        chart_id=str(preview.get("chart_id") or ""),
        title=str(preview.get("title") or ""),
    )
    narrative = build_chart_narrative(
        chart_id=str(preview.get("chart_id") or ""),
        title=str(preview.get("title") or ""),
        stats=stats,
        fault_summary=fault_summary,
    )
    return {**preview, "stats": stats, "stats_bullets": stats.get("stats_bullets") or [], "narrative": narrative}


def _plotly_preview(
    *,
    chart_id: str,
    title: str,
    plotted: dict[str, Any],
    readings: dict[str, Any],
    fault_summary: dict[str, Any],
    warnings: list[str] | None = None,
    gallery_mode: bool = False,
) -> dict[str, Any]:
    raw = {
        "chart_id": chart_id,
        "title": title,
        "image_base64": plotted.get("image_base64") or "",
        "warnings": warnings or [],
        "row_count": plotted.get("row_count") or readings.get("row_count") or 0,
    }
    if not gallery_mode:
        raw["plotly_figure"] = plotted.get("figure")
    return _enrich_preview(raw, readings, fault_summary=fault_summary)


def _json_safe_overlays(overlays: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for ov in overlays:
        row = dict(ov)
        for key in ("x0", "x1"):
            val = row.get(key)
            if hasattr(val, "isoformat"):
                row[key] = val.isoformat()
        safe.append(row)
    return safe


def _subset_readings(batch: dict[str, Any], cols: list[str]) -> dict[str, Any]:
    if not batch:
        return {}
    col_set = set(cols)
    series = batch.get("series") if isinstance(batch.get("series"), dict) else {}
    labels = batch.get("labels") if isinstance(batch.get("labels"), dict) else {}
    fault_plots = batch.get("fault_plots") if isinstance(batch.get("fault_plots"), dict) else {}
    return {
        "timestamps": batch.get("timestamps") or [],
        "series": {k: v for k, v in series.items() if k in col_set},
        "labels": {k: v for k, v in labels.items() if k in col_set},
        "fault_plots": fault_plots,
        "fault_panels": batch.get("fault_panels") or [],
        "row_count": batch.get("row_count") or len(batch.get("timestamps") or []),
    }


def _build_diagnostics(
    tree: dict[str, Any],
    *,
    available: list[dict[str, Any]],
    disabled: list[dict[str, Any]],
    fault_summary: dict[str, Any],
) -> dict[str, Any]:
    role_map: dict[str, str] = {}
    for spec in CHART_SPECS:
        roles = spec.get("required_roles") or []
        if not roles:
            continue
        cols, missing = resolve_roles_on_tree(tree, roles)
        if cols:
            role_map[str(spec.get("chart_id"))] = ", ".join(cols)
        if missing:
            role_map[f"{spec.get('chart_id')}_missing"] = ", ".join(missing)
    hints: list[str] = []
    if not fault_summary.get("active_faults"):
        hints.append("No active faults in window — fault bar charts are skipped; HVAC trend charts still render.")
    if disabled:
        hints.append(f"{len(disabled)} chart(s) unavailable — expand “Unavailable charts” for role/column gaps.")
    if not hints:
        hints.append("Data looks ready — click Render chart gallery.")
    return {
        "roles_resolved": role_map,
        "available_count": len(available),
        "disabled_count": len(disabled),
        "hints": hints,
    }


def build_rcx_preview(
    *,
    site_id: str = "",
    hours: int = 24,
    start: str | None = None,
    end: str | None = None,
    chart_ids: list[str] | None = None,
    bundle_ids: list[str] | None = None,
    custom_columns: list[str] | None = None,
    show_fault_overlays: bool = True,
    include_previews: bool = True,
    catalog_only: bool = False,
    gallery_mode: bool = False,
    scope: str = "building",
    equipment_ids: list[str] | None = None,
) -> dict[str, Any]:
    win_start, win_end, eff_hours = _window(hours, start=start, end=end)
    sid, site_name = _resolve_site(site_id)

    def _mech_payload(*, full: bool) -> dict[str, Any]:
        narr = build_mechanical_narrative(sid, fast=not full)
        payload: dict[str, Any] = {
            "narrative": narr.get("narrative"),
            "counts": narr.get("counts"),
        }
        if full:
            detail = build_mechanical_summary(sid, hours=eff_hours)
            payload.update(detail)
            payload["narrative"] = narr.get("narrative")
            payload["counts"] = narr.get("counts")
        return payload

    try:
        tree = query_model_tree()
    except Exception:
        tree = {"equipment": [], "points": []}

    overview = build_overview(site_id=sid)
    faults_data = build_fault_analytics(hours=eff_hours)
    try:
        eq_pts = run_fdd_preset("equipment_to_points", site_id=sid)
    except KeyError:
        eq_pts = {"rows": [], "columns": []}

    mech = _mech_payload(full=not gallery_mode and not catalog_only)

    fault_rows = faults_data.get("faults") if isinstance(faults_data.get("faults"), list) else []
    equipment_meta = {
        str(e.get("id") or e.get("equipment_id") or ""): e
        for e in (tree.get("equipment") or [])
        if isinstance(e, dict) and (e.get("id") or e.get("equipment_id"))
    }
    report_model = build_report_bundles(
        equipment_rows=eq_pts.get("rows") or [],
        equipment_meta=equipment_meta,
        fault_rows=fault_rows,
    )
    bundles = report_model.get("bundles") or []
    equipment_charts = report_model.get("equipment_charts") or []
    use_model_bundles = bool(equipment_charts)

    if bundle_ids is not None:
        chart_ids = chart_ids_for_bundles(bundles, bundle_ids)
    elif not chart_ids and bundles:
        chart_ids = chart_ids_for_bundles(bundles, report_model.get("default_bundle_ids") or [])

    roles_present = canonical_roles_present(tree)
    has_faults = bool(fault_rows)
    trend_cache: dict[str, dict[str, Any]] = {}
    fault_summary = {
        "active_faults": len(fault_rows),
        "total_fault_hours": (overview.get("kpis") or {}).get("total_fault_hours"),
    }

    def _readings_for_columns(cols: list[str]) -> dict[str, Any]:
        key = ",".join(cols)
        if key in trend_cache:
            return trend_cache[key]
        if not cols:
            trend_cache[key] = {}
            return {}
        try:
            data = read_chart_readings_with_plot_fallback(
                sid,
                cols,
                hours=eff_hours,
                include_faults=show_fault_overlays,
            )
        except Exception:
            data = {}
        trend_cache[key] = data
        return data

    def _readings_for_chart(chart_id: str) -> dict[str, Any]:
        roles = TREND_CHARTS.get(chart_id)
        if not roles:
            return {}
        return _readings_for_columns(columns_for_roles(tree, roles, equipment_ids=equipment_ids))

    render_previews = include_previews and not catalog_only
    batch_readings: dict[str, Any] = {}
    if render_previews:
        cols_needed: list[str] = []
        for spec in CHART_SPECS:
            cid = spec["chart_id"]
            if chart_ids and cid not in chart_ids:
                continue
            if use_model_bundles and cid in TREND_CHART_IDS:
                continue
            if cid in TREND_CHARTS:
                cols, _ = resolve_roles_on_tree(
                    tree, spec.get("required_roles") or [], equipment_ids=equipment_ids
                )
                cols_needed.extend(cols)
        for col in custom_columns or []:
            c = str(col).strip()
            if c:
                cols_needed.append(c)
        for eq_chart in equipment_charts_for_ids(equipment_charts, chart_ids or []):
            for c in eq_chart.get("columns") or []:
                if c and c not in cols_needed:
                    cols_needed.append(str(c))
        cols_needed = list(dict.fromkeys(cols_needed))
        if cols_needed:
            batch_readings = _readings_for_columns(cols_needed)

    available: list[dict[str, Any]] = []
    disabled: list[dict[str, Any]] = []
    previews: list[dict[str, Any]] = []

    for spec in CHART_SPECS:
        if chart_ids and spec["chart_id"] not in chart_ids:
            continue
        if use_model_bundles and spec["chart_id"] in TREND_CHART_IDS:
            continue
        cid = spec["chart_id"]
        if cid in TREND_CHARTS:
            cols, _missing = resolve_roles_on_tree(
                tree, spec.get("required_roles") or [], equipment_ids=equipment_ids
            )
            trend_ok = bool(cols)
            if render_previews and cols:
                sub = _subset_readings(batch_readings, cols) if batch_readings else _readings_for_columns(cols)
                trend_ok = (sub.get("row_count") or 0) > 0
        elif render_previews:
            trend_ok = bool((batch_readings.get("row_count") or 0) > 0)
        else:
            trend_ok = True
        ok, reason = chart_readiness(
            spec,
            roles_present=roles_present,
            has_fault_data=has_faults,
            has_trend_data=trend_ok if cid in TREND_CHARTS else True,
            tree=tree,
        )
        if ok:
            entry = dict(spec)
            if reason:
                entry["partial_note"] = reason
            available.append(entry)
        else:
            disabled.append({**spec, "reason": reason})

    available_ids = {str(s["chart_id"]) for s in available}
    for eq_chart in equipment_charts:
        cid = str(eq_chart.get("chart_id") or "")
        if not cid:
            continue
        if chart_ids and cid not in chart_ids:
            continue
        available.append(
            {
                "chart_id": cid,
                "title": eq_chart.get("title"),
                "equipment_type": eq_chart.get("family"),
                "equipment_id": eq_chart.get("equipment_id"),
                "required_roles": [],
                "supports_fault_overlay": True,
                "supports_preview": True,
                "supports_docx": True,
            }
        )
        available_ids.add(cid)

    suggested_chart_ids = chart_ids_for_bundles(bundles, bundle_ids or report_model.get("default_bundle_ids") or [])

    base_payload = {
        "site_id": sid,
        "site": sid,
        "site_name": site_name,
        "window": {"start": win_start, "end": win_end, "hours": eff_hours},
        "scope": scope,
        "equipment": equipment_ids or [],
        "mechanical_summary": mech,
        "available_charts": available,
        "disabled_charts": disabled,
        "sections": SECTION_SPECS,
        "suggested_chart_ids": suggested_chart_ids,
        "fault_summary": fault_summary,
        "fault_rows": fault_rows[:50],
        "fault_overlays": [],
        "chart_previews": [],
        "report_bundles": report_model,
        "diagnostics": _build_diagnostics(
            tree, available=available, disabled=disabled, fault_summary=fault_summary
        ),
        "warnings": mech.get("warnings") or [],
        "missing_roles": [
            str(i.get("title") or "") for i in (mech.get("model_issues") or [])[:10]
        ],
    }

    if not render_previews:
        return base_payload

    by_sev = overview.get("faults_by_severity") or faults_data.get("fault_count_by_severity") or []
    if has_faults and (not chart_ids or "fault_hours_by_severity" in (chart_ids or [])):
        labels = [r.get("group", "") for r in by_sev]
        values = [float(r.get("elapsed_hours") or 0) for r in by_sev]
        plotted = build_bar_figure(title="Fault hours by severity", labels=labels, values=values, plotly=not gallery_mode)
        previews.append(
            _plotly_preview(
                chart_id="fault_hours_by_severity",
                title="Fault hours by severity",
                plotted=plotted,
                readings={"timestamps": [], "series": {}, "row_count": len(fault_rows)},
                fault_summary=fault_summary,
                gallery_mode=gallery_mode,
            )
        )

    by_eq = overview.get("fault_hours_by_equipment") or faults_data.get("fault_hours_by_equipment") or []
    if has_faults and (not chart_ids or "fault_hours_by_equipment" in (chart_ids or [])):
        labels = [str(r.get("group", ""))[:20] for r in by_eq[:12]]
        values = [float(r.get("elapsed_hours") or 0) for r in by_eq[:12]]
        plotted = build_bar_figure(title="Fault hours by equipment", labels=labels, values=values, plotly=not gallery_mode)
        previews.append(
            _plotly_preview(
                chart_id="fault_hours_by_equipment",
                title="Fault hours by equipment",
                plotted=plotted,
                readings={"timestamps": [], "series": {}, "row_count": len(fault_rows)},
                fault_summary=fault_summary,
                gallery_mode=gallery_mode,
            )
        )

    if not chart_ids or "building_inventory" in (chart_ids or []):
        if "building_inventory" in available_ids:
            mh = build_model_health()
            inv_counts = mech.get("counts") if isinstance(mech.get("counts"), dict) else {}
            plotted = build_building_inventory_figure(
                counts=inv_counts,
                fault_summary=fault_summary,
                model_health=mh if isinstance(mh, dict) else {},
                plotly=not gallery_mode,
            )
            previews.append(
                _plotly_preview(
                    chart_id="building_inventory",
                    title="Building inventory & active faults",
                    plotted=plotted,
                    readings={"timestamps": [], "series": {}, "row_count": 0},
                    fault_summary=fault_summary,
                    gallery_mode=gallery_mode,
                )
            )

    for chart_id, roles in TREND_CHARTS.items():
        if use_model_bundles:
            break
        if chart_ids and chart_id not in chart_ids:
            continue
        if chart_id not in available_ids:
            continue
        cols, _missing = resolve_roles_on_tree(tree, roles, equipment_ids=equipment_ids)
        if not cols:
            continue
        readings = _subset_readings(batch_readings, cols) if batch_readings else _readings_for_columns(cols)
        title = next((s["title"] for s in CHART_SPECS if s["chart_id"] == chart_id), chart_id)
        partial = [s.get("partial_note") for s in available if s.get("chart_id") == chart_id]
        plotted = build_trend_figure(
            readings, title=title, show_faults=show_fault_overlays, plotly=not gallery_mode
        )
        previews.append(
            _plotly_preview(
                chart_id=chart_id,
                title=title,
                plotted=plotted,
                readings=readings,
                fault_summary=fault_summary,
                warnings=[partial[0]] if partial and partial[0] else [],
                gallery_mode=gallery_mode,
            )
        )

    for eq_chart in equipment_charts_for_ids(equipment_charts, chart_ids or []):
        cols = [str(c) for c in (eq_chart.get("columns") or []) if c]
        if not cols:
            continue
        readings = _subset_readings(batch_readings, cols) if batch_readings else _readings_for_columns(cols)
        title = str(eq_chart.get("title") or eq_chart.get("chart_id"))
        plotted = build_trend_figure(
            readings, title=title, show_faults=show_fault_overlays, plotly=not gallery_mode
        )
        previews.append(
            _plotly_preview(
                chart_id=str(eq_chart.get("chart_id")),
                title=title,
                plotted=plotted,
                readings=readings,
                fault_summary=fault_summary,
                gallery_mode=gallery_mode,
            )
        )

    for col in custom_columns or []:
        col = str(col).strip()
        if not col:
            continue
        if chart_ids and f"custom_{col}" not in chart_ids and col not in chart_ids:
            continue
        readings = _subset_readings(batch_readings, [col]) if batch_readings else _readings_for_columns([col])
        labels = readings.get("labels") if isinstance(readings.get("labels"), dict) else {}
        title = str(labels.get(col) or col)
        chart_key = f"custom_{col}"
        plotted = build_trend_figure(
            readings, title=title, show_faults=show_fault_overlays, plotly=not gallery_mode
        )
        previews.append(
            _plotly_preview(
                chart_id=chart_key,
                title=f"Custom: {title}",
                plotted=plotted,
                readings=readings,
                fault_summary=fault_summary,
                gallery_mode=gallery_mode,
            )
        )
        available.append(
            {
                "chart_id": chart_key,
                "title": f"Custom: {title}",
                "equipment_type": "custom",
                "required_roles": [],
                "supports_fault_overlay": True,
                "supports_preview": True,
                "supports_docx": True,
            }
        )

    fault_overlays: list[dict[str, Any]] = []
    if show_fault_overlays and not gallery_mode:
        for chart_id in TREND_CHARTS:
            roles = TREND_CHARTS.get(chart_id) or []
            cols = columns_for_roles(tree, roles, equipment_ids=equipment_ids)
            rd = _subset_readings(batch_readings, cols) if batch_readings else _readings_for_chart(chart_id)
            fault_overlays.extend(overlays_from_readings(rd, show=True)[:8])

    return {
        **base_payload,
        "fault_overlays": _json_safe_overlays(fault_overlays),
        "chart_previews": previews,
    }


def generate_rcx_docx(
    *,
    site_id: str = "",
    hours: int = 24,
    start: str | None = None,
    end: str | None = None,
    sections: list[str] | None = None,
    charts: list[str] | None = None,
    custom_columns: list[str] | None = None,
    show_fault_overlays: bool = True,
    bundle_ids: list[str] | None = None,
    equipment_ids: list[str] | None = None,
    include_previews: bool = False,
) -> tuple[bytes, str]:
    preview = build_rcx_preview(
        site_id=site_id,
        hours=hours,
        start=start,
        end=end,
        chart_ids=charts,
        custom_columns=custom_columns,
        show_fault_overlays=show_fault_overlays,
        catalog_only=not include_previews,
        include_previews=include_previews,
        gallery_mode=include_previews,
        bundle_ids=bundle_ids,
        equipment_ids=equipment_ids,
    )
    sid, site_name = _resolve_site(site_id)
    fault_rows = preview.get("fault_rows") or []

    from open_fdd.reports.rcx_docx import build_rcx_docx
    from .rcx_report_context import build_rcx_report_context

    mech = preview.get("mechanical_summary") or {}
    overview = {
        "active_faults": preview["fault_summary"]["active_faults"],
        "total_fault_hours": preview["fault_summary"]["total_fault_hours"],
        "missing_roles": preview.get("missing_roles"),
        "mechanical_summary": mech,
        "model_health": mech.get("model_health") if isinstance(mech.get("model_health"), dict) else {},
    }
    report_ctx = build_rcx_report_context(site_id=sid, hours=preview.get("window", {}).get("hours") or hours)
    bundles = (preview.get("report_bundles") or {}).get("bundles") or []
    equipment_charts = (preview.get("report_bundles") or {}).get("equipment_charts") or []
    equipment_bundle = None
    if charts:
        for b in bundles:
            chart_ids = b.get("chart_ids") or []
            if any(c in chart_ids for c in charts):
                equipment_bundle = b
                break

    blob = build_rcx_docx(
        site_id=sid,
        site_name=site_name,
        window=preview.get("window") or {},
        fault_rows=fault_rows,
        overview=overview,
        sections=sections,
        charts=charts,
        warnings=preview.get("warnings"),
        chart_previews=preview.get("chart_previews") or [],
        report_context=report_ctx,
        equipment_bundle=equipment_bundle,
        equipment_charts=equipment_charts,
        available_charts=preview.get("available_charts") or [],
        disabled_charts=preview.get("disabled_charts") or [],
    )
    start_s = (preview.get("window") or {}).get("start", "")[:10]
    end_s = (preview.get("window") or {}).get("end", "")[:10]
    fname = f"openfdd-rcx-{sid}-{start_s}-{end_s}.docx"
    return blob, fname
