"""Chat/agent-driven RCx report planning and generation."""

from __future__ import annotations

import re
from typing import Any

from .chart_preview import build_rcx_preview, generate_rcx_docx
from .chart_specs import suggest_charts_for_faults
from .rcx_points import list_report_points
from .report_profile import plan_report_from_model

DEFAULT_INTENT_SECTIONS = [
    "executive_summary",
    "mechanical_summary",
    "trend_charts",
    "fault_analytics",
    "analyst_insights",
    "appendix_faults",
]

_TOKEN_SPLIT = re.compile(r"[,;\n]+")


def _split_tokens(raw: list[str] | str | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = _TOKEN_SPLIT.split(raw.strip())
    else:
        parts = []
        for item in raw:
            parts.extend(_TOKEN_SPLIT.split(str(item).strip()))
    return [p.strip() for p in parts if p and p.strip()]


def resolve_sensor_columns(
    site_id: str,
    sensors: list[str] | str | None,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """Map human sensor names / point ids / columns to historian columns."""
    tokens = _split_tokens(sensors)
    catalog = list_report_points(site_id, limit=limit)
    points = catalog.get("points") or []
    if not tokens:
        return {
            "site_id": catalog.get("site_id"),
            "columns": [],
            "matches": [],
            "unresolved": [],
            "catalog_count": len(points),
        }

    resolved_cols: list[str] = []
    matches: list[dict[str, Any]] = []
    unresolved: list[str] = []

    def _score(pt: dict[str, Any], token: str) -> int:
        col = str(pt.get("column") or "").lower()
        label = str(pt.get("label") or "").lower()
        pid = str(pt.get("point_id") or "").lower()
        eq = str(pt.get("equipment_name") or "").lower()
        tok = token.lower()
        if tok == col or tok == pid:
            return 100
        if tok == label:
            return 90
        if col == tok.replace(" ", "-") or col == tok.replace(" ", "_"):
            return 85
        if tok in label or label in tok:
            return 70
        if tok in col:
            return 65
        if tok in eq and ("temp" in label or "humid" in label or "rh" in label):
            return 55
        if tok in str(pt.get("brick_type") or "").lower():
            return 50
        return 0

    for token in tokens:
        ranked = sorted(
            (( _score(pt, token), pt) for pt in points if isinstance(pt, dict)),
            key=lambda x: x[0],
            reverse=True,
        )
        best_score, best = ranked[0] if ranked else (0, None)
        if best_score >= 50 and best:
            col = str(best.get("column") or "")
            if col and col not in resolved_cols:
                resolved_cols.append(col)
                matches.append(
                    {
                        "token": token,
                        "column": col,
                        "label": best.get("label"),
                        "point_id": best.get("point_id"),
                        "equipment_name": best.get("equipment_name"),
                        "score": best_score,
                    }
                )
            elif col:
                matches.append({"token": token, "column": col, "duplicate": True, "score": best_score})
            else:
                unresolved.append(token)
        else:
            unresolved.append(token)

    return {
        "site_id": catalog.get("site_id"),
        "columns": resolved_cols,
        "matches": matches,
        "unresolved": unresolved,
        "catalog_count": len(points),
    }


def plan_rcx_report_intent(
    *,
    site_id: str = "",
    hours: int = 168,
    start: str | None = None,
    end: str | None = None,
    sensors: list[str] | str | None = None,
    sensor_columns: list[str] | None = None,
    show_fault_overlays: bool = True,
    bundle_ids: list[str] | None = None,
    equipment_ids: list[str] | None = None,
    include_analytics: bool = True,
) -> dict[str, Any]:
    """Build a generation plan: sections, charts, resolved sensors, readiness."""
    sensor_res = resolve_sensor_columns(site_id, sensors)
    columns = list(dict.fromkeys([*(sensor_columns or []), *(sensor_res.get("columns") or [])]))

    preview = build_rcx_preview(
        site_id=site_id,
        hours=hours,
        start=start,
        end=end,
        custom_columns=columns or None,
        show_fault_overlays=show_fault_overlays,
        include_previews=False,
        catalog_only=True,
        bundle_ids=bundle_ids,
        equipment_ids=equipment_ids,
    )

    available = preview.get("available_charts") or []
    available_ids = {str(c.get("chart_id") or "") for c in available if c.get("chart_id")}
    fault_rows = preview.get("fault_rows") or []
    mech = preview.get("mechanical_summary") or {}

    tree: dict[str, Any] = {}
    try:
        from ..model_sparql import query_model_tree

        tree = query_model_tree()
    except Exception:
        pass

    model_plan = plan_report_from_model(
        mechanical_summary=mech,
        report_bundles=preview.get("report_bundles"),
        equipment=tree.get("equipment") if isinstance(tree.get("equipment"), list) else [],
        points=tree.get("points") if isinstance(tree.get("points"), list) else [],
        fault_rows=fault_rows,
        available_chart_ids=available_ids,
        custom_columns=columns or None,
        include_analytics=include_analytics,
    )

    charts = list(model_plan.get("charts") or [])
    if bundle_ids:
        from .report_bundles import chart_ids_for_bundles

        bundles = (preview.get("report_bundles") or {}).get("bundles") or []
        for cid in chart_ids_for_bundles(bundles, bundle_ids):
            if cid not in charts:
                charts.append(cid)

    sections = list(model_plan.get("sections") or DEFAULT_INTENT_SECTIONS)

    ready = bool(preview.get("available_charts")) or bool(columns)
    warnings = list(preview.get("warnings") or [])
    if sensor_res.get("unresolved"):
        warnings.append(f"Unresolved sensors: {', '.join(sensor_res['unresolved'])}")
    if not columns and not charts:
        warnings.append("No charts selected — add sensors or ensure historian data exists.")

    return {
        "ok": ready,
        "site_id": preview.get("site_id"),
        "site_name": preview.get("site_name"),
        "window": preview.get("window"),
        "sensors": sensor_res,
        "sections": sections,
        "charts": charts[:24],
        "show_fault_overlays": show_fault_overlays,
        "fault_summary": preview.get("fault_summary"),
        "available_chart_count": len(available),
        "disabled_chart_count": len(preview.get("disabled_charts") or []),
        "mechanical_summary": preview.get("mechanical_summary"),
        "report_profile": {
            "profile_id": model_plan.get("profile_id"),
            "profile_label": model_plan.get("profile_label"),
            "report_type": model_plan.get("report_type"),
            "emphasis": model_plan.get("emphasis"),
            "rationale": model_plan.get("rationale"),
            "topology": model_plan.get("topology"),
        },
        "warnings": warnings,
        "suggested_chart_ids": preview.get("suggested_chart_ids") or [],
    }


def generate_rcx_report_from_intent(
    *,
    site_id: str = "",
    hours: int = 168,
    start: str | None = None,
    end: str | None = None,
    sensors: list[str] | str | None = None,
    sensor_columns: list[str] | None = None,
    show_fault_overlays: bool = True,
    bundle_ids: list[str] | None = None,
    equipment_ids: list[str] | None = None,
    sections: list[str] | None = None,
    charts: list[str] | None = None,
    include_analytics: bool = True,
    include_previews: bool = True,
    save_to_volume: bool = True,
) -> dict[str, Any]:
    """Single-shot RCx report for chat/agents: plan → preview charts → DOCX."""
    plan = plan_rcx_report_intent(
        site_id=site_id,
        hours=hours,
        start=start,
        end=end,
        sensors=sensors,
        sensor_columns=sensor_columns,
        show_fault_overlays=show_fault_overlays,
        bundle_ids=bundle_ids,
        equipment_ids=equipment_ids,
        include_analytics=include_analytics,
    )
    use_sections = [s for s in (sections or plan.get("sections") or []) if s]
    use_charts = [c for c in (charts or plan.get("charts") or []) if c]
    columns = list(plan.get("sensors", {}).get("columns") or [])

    docx_bytes, fname = generate_rcx_docx(
        site_id=str(plan.get("site_id") or site_id),
        hours=hours,
        start=start,
        end=end,
        sections=use_sections or None,
        charts=use_charts or None,
        custom_columns=columns or None,
        show_fault_overlays=show_fault_overlays,
        bundle_ids=bundle_ids,
        equipment_ids=equipment_ids,
        include_previews=include_previews,
    )

    saved = False
    if save_to_volume:
        from .report_store import save_report

        save_report(fname, docx_bytes)
        saved = True

    preview_summary = build_rcx_preview(
        site_id=str(plan.get("site_id") or site_id),
        hours=hours,
        start=start,
        end=end,
        chart_ids=use_charts or None,
        custom_columns=columns or None,
        show_fault_overlays=show_fault_overlays,
        include_previews=True,
        catalog_only=False,
        gallery_mode=True,
        bundle_ids=bundle_ids,
        equipment_ids=equipment_ids,
    )
    chart_previews = preview_summary.get("chart_previews") or []
    slim_previews = [
        {
            "chart_id": p.get("chart_id"),
            "title": p.get("title"),
            "row_count": p.get("row_count"),
            "narrative": p.get("narrative"),
            "has_image": bool(p.get("image_base64")),
        }
        for p in chart_previews
        if isinstance(p, dict)
    ]

    return {
        "ok": True,
        "filename": fname,
        "bytes": len(docx_bytes),
        "saved_to_volume": saved,
        "download_path": f"/api/reports/rcx/download/{fname}",
        "plan": plan,
        "chart_previews": slim_previews,
        "chart_preview_count": len(slim_previews),
        "fault_summary": plan.get("fault_summary"),
        "warnings": plan.get("warnings") or [],
    }
