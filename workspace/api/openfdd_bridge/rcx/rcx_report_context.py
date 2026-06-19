"""Gather programmatic RCx report context (faults, rules, motors, overrides)."""

from __future__ import annotations

from typing import Any

from ..model_sparql import query_model_tree
from ..rule_store import RuleStore
from ..timeseries_api import plot_column_name
from .motor_runtime import weekly_motor_runtime
from .trend_charts import historian_column_for_point


def _point_by_id(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for pt in model.get("points") or []:
        if isinstance(pt, dict):
            pid = str(pt.get("id") or "").strip()
            if pid:
                out[pid] = pt
    return out


def _override_summary() -> dict[str, Any]:
    try:
        from bacnet_toolshed.override_registry import override_dashboard_summary, slim_overrides_for_llm

        summary = override_dashboard_summary(preview_limit=8)
        slim = slim_overrides_for_llm(limit=64)
        return {**slim, **summary}
    except Exception:
        return {"override_count": 0, "overrides": [], "preview": [], "by_device": []}


def assigned_rules_with_sensors(
    *,
    site_id: str,
    model: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rule Lab rules with bound sensor columns for screenshot placeholders."""
    if model is None:
        from ..model_service import ModelService

        model = ModelService().load()
    points = _point_by_id(model)
    rows: list[dict[str, Any]] = []
    for rule in RuleStore().list_rules():
        if not isinstance(rule, dict) or not rule.get("enabled", True):
            continue
        if rule.get("mode") != "rule":
            continue
        bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
        point_ids = [str(x) for x in bindings.get("point_ids") or [] if str(x).strip()]
        equipment_ids = [str(x) for x in bindings.get("equipment_ids") or [] if str(x).strip()]
        sensors: list[dict[str, str]] = []
        for pid in point_ids:
            pt = points.get(pid)
            if not pt:
                continue
            col = historian_column_for_point(pt) or plot_column_name(pt)
            sensors.append(
                {
                    "point_id": pid,
                    "column": col,
                    "label": str(pt.get("name") or col),
                    "brick_type": str(pt.get("brick_type") or ""),
                    "equipment_id": str(pt.get("equipment_id") or ""),
                }
            )
        cfg = rule.get("config") if isinstance(rule.get("config"), dict) else {}
        value_col = str(cfg.get("value_column") or "").strip()
        if value_col and not any(s["column"] == value_col for s in sensors):
            sensors.append({"point_id": "", "column": value_col, "label": value_col, "brick_type": "", "equipment_id": ""})
        rows.append(
            {
                "rule_id": str(rule.get("id") or ""),
                "rule_name": str(rule.get("name") or ""),
                "fault_code": str(rule.get("fault_code") or ""),
                "severity": str(rule.get("severity") or "warning"),
                "equipment_ids": equipment_ids,
                "sensors": sensors,
            }
        )
    return rows


def build_rcx_report_context(
    *,
    site_id: str,
    hours: int = 168,
) -> dict[str, Any]:
    """Programmatic payload for DOCX (no chart PNGs required)."""
    try:
        tree = query_model_tree()
    except Exception:
        tree = {"equipment": [], "points": []}

    from ..model_service import ModelService

    model = ModelService().load()
    rules = assigned_rules_with_sensors(site_id=site_id, model=model)
    motors = weekly_motor_runtime(site_id, tree, hours=hours)
    overrides = _override_summary()

    return {
        "assigned_rules": rules,
        "motor_runtime": motors,
        "overrides": overrides,
        "override_count": int(overrides.get("operator_override_points") or overrides.get("override_count") or 0),
        "override_scan": overrides.get("scan") if isinstance(overrides.get("scan"), dict) else {},
        "override_scan_health": overrides.get("scan_health") if isinstance(overrides.get("scan_health"), dict) else {},
        "override_by_device": overrides.get("by_device") if isinstance(overrides.get("by_device"), list) else [],
        "override_preview": overrides.get("preview") if isinstance(overrides.get("preview"), list) else [],
    }
