"""Elapsed fault-hour analytics from FDD run records and alert lists."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _hours_from_analytics(analytics: dict[str, Any]) -> float:
    if not analytics:
        return 0.0
    sec = analytics.get("estimated_fault_duration_sec")
    if sec is None:
        sec = analytics.get("fault_span_sec")
    if sec is None:
        fs = analytics.get("fault_samples")
        period = analytics.get("sample_period_sec") or 3600.0
        if fs is not None:
            try:
                sec = float(fs) * float(period)
            except (TypeError, ValueError):
                sec = 0.0
    try:
        return max(0.0, float(sec or 0) / 3600.0)
    except (TypeError, ValueError):
        return 0.0


def fault_hours_from_fdd_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per (equipment, fault_code) with elapsed hours from latest FDD runs."""
    rows: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        flagged = int(run.get("flagged") or 0)
        if flagged <= 0:
            continue
        analytics = run.get("analytics") if isinstance(run.get("analytics"), dict) else {}
        hours = _hours_from_analytics(analytics)
        if hours <= 0 and flagged > 0:
            rows_eval = int(run.get("rows") or 0)
            if rows_eval > 0:
                hours = flagged / max(rows_eval, 1)
        eq = str(run.get("equipment_name") or "").strip()
        if not eq:
            names = run.get("equipment_names")
            if isinstance(names, list) and names:
                eq = str(names[0] or "").strip()
        symptom = str(run.get("symptom") or "").strip() or str(run.get("rule_name") or "")
        rows.append(
            {
                "site_id": str(run.get("site_id") or ""),
                "equipment": eq or "—",
                "equipment_type": str(run.get("equipment_family") or run.get("equipment_type") or ""),
                "rule_id": str(run.get("rule_id") or ""),
                "fault_name": symptom,
                "short_description": str(run.get("short_description") or symptom),
                "symptom": symptom,
                "data_source": str(run.get("data_source") or ""),
                "severity": str(run.get("severity") or "warning"),
                "elapsed_hours": round(hours, 3),
                "samples_flagged": flagged,
                "samples_evaluated": int(run.get("rows") or 0),
                "rule_id": str(run.get("rule_id") or ""),
            }
        )
    return rows


def aggregate_fault_hours(
    rows: list[dict[str, Any]],
    *,
    group_by: str = "equipment",
) -> list[dict[str, Any]]:
    """Sum elapsed hours grouped by equipment, fault_code, or severity."""
    totals: dict[tuple[str, ...], float] = defaultdict(float)
    meta: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key_field = {
            "equipment": row.get("equipment") or "—",
            "fault_code": row.get("fault_code") or row.get("rule_id") or "—",
            "rule_id": row.get("rule_id") or "—",
            "fault_name": row.get("fault_name") or row.get("short_description") or "—",
            "severity": row.get("severity") or "warning",
            "site_id": row.get("site_id") or "",
        }.get(group_by, row.get(group_by) or "—")
        key = (str(key_field),)
        try:
            totals[key] += float(row.get("elapsed_hours") or 0)
        except (TypeError, ValueError):
            pass
        meta[key] = {**row, group_by: key_field}
    out: list[dict[str, Any]] = []
    for key, hours in sorted(totals.items(), key=lambda kv: -kv[1]):
        base = dict(meta.get(key, {}))
        base["elapsed_hours"] = round(hours, 3)
        base["group"] = key[0]
        out.append(base)
    return out


def fault_hours_from_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build fault-hour rows from check-engine alert dicts (source=fdd)."""
    rows: list[dict[str, Any]] = []
    for alert in alerts:
        if str(alert.get("source") or "") != "fdd":
            continue
        analytics = alert.get("analytics") if isinstance(alert.get("analytics"), dict) else {}
        hours = _hours_from_analytics(analytics)
        ctx = alert.get("model_context") if isinstance(alert.get("model_context"), dict) else {}
        eq = ctx.get("equipment") if isinstance(ctx.get("equipment"), dict) else {}
        symptom = str(alert.get("short_description") or alert.get("symptom") or ctx.get("short_description") or alert.get("rule_name") or "").strip()
        rows.append(
            {
                "site_id": str(alert.get("site_id") or ""),
                "equipment": str(
                    alert.get("equipment_name")
                    or eq.get("name")
                    or alert.get("title")
                    or "—"
                ),
                "equipment_type": str(eq.get("type") or alert.get("equipment_family") or ""),
                "rule_id": str(alert.get("rule_id") or ""),
                "fault_name": symptom or str(alert.get("rule_name") or alert.get("title") or ""),
                "short_description": symptom,
                "symptom": symptom,
                "data_source": str(alert.get("data_source") or ctx.get("data_source") or ""),
                "severity": str(alert.get("severity") or "warning"),
                "elapsed_hours": round(hours, 3),
                "samples_flagged": analytics.get("fault_samples"),
                "samples_evaluated": analytics.get("total_samples"),
            }
        )
    return rows
