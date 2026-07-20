"""Shared rule-card content for Plots UI + DOCX (params + role mapping + catalog meta)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.rule_plot_meta import (
    analytics_hint,
    analytics_related,
    catalog_fields,
    catalog_facts_pairs,
    data_model_fit,
    haystack_tag,
    plot_series_bullets,
    points_haystack_note,
)
from app.rules.base import RuleResult
from app.rules.cookbook_catalog import CookbookRule


# Meta keys in role_map blocks that are not CSV column → role bindings.
_ROLE_MAP_META = frozenset(
    {
        "equipment_type",
        "equipType",
        "plant_group",
        "chw_pump_equipment",
    }
)


@dataclass(frozen=True)
class ParamRow:
    key: str
    label: str
    unit: str
    value: float
    default: float
    source: str  # "override" | "default"
    min: float = 0.0
    max: float = 0.0
    step: float = 0.0


@dataclass(frozen=True)
class MappingRow:
    role: str
    haystack_tag: str
    csv_column: str
    requirement: str  # "required" | "optional"
    in_history: bool
    present: bool  # alias clarity for UI — same as in_history when mapped_df given


@dataclass
class RuleCard:
    rule_id: str
    title: str
    family: str
    equation: str
    description: str
    status: str
    fault_hours: float | None
    missing_roles: list[str]
    notes: str
    param_rows: list[ParamRow] = field(default_factory=list)
    mapping_rows: list[MappingRow] = field(default_factory=list)
    required_roles_total: int = 0
    required_roles_present: int = 0
    coverage_pct: float | None = None  # % required roles present (None if no required roles)
    has_result: bool = False
    plottable: bool = False
    # Catalog-parity fields (RULE_PLOT_CATALOG.md)
    equipment_kinds: list[str] = field(default_factory=list)
    gate_mode: str = "—"
    confirm_seconds: float = 300.0
    sensor_sweep: bool = False
    control_output_sweep: bool = False
    sweep_label: str = "—"
    plot_series: list[str] = field(default_factory=list)
    points_note: str = ""
    analytics_hint: str = ""
    analytics_fit: list[str] = field(default_factory=list)
    rcx_preset_ids: tuple[str, ...] = ()
    catalog_facts: list[tuple[str, str]] = field(default_factory=list)


def csv_column_for_role(role: str, equipment_id: str, role_map: dict) -> str:
    """Resolve CSV column bound to a cookbook role for one equipment.

    Canonical role_map shape is ``{csv_column: cookbook_role}``. Also accepts
    reverse ``{cookbook_role: csv_column}`` for convenience.
    """
    block = role_map.get(equipment_id) or {}
    if not isinstance(block, dict):
        return ""
    for col, mapped_role in block.items():
        if col in _ROLE_MAP_META:
            continue
        if str(mapped_role).strip() == role:
            return str(col)
    if role in block and isinstance(block[role], str) and role not in _ROLE_MAP_META:
        return str(block[role]).strip()
    return ""


def mapping_rows_for_rule(
    rule: CookbookRule,
    equipment_id: str,
    role_map: dict,
    mapped_df: pd.DataFrame | None,
) -> list[MappingRow]:
    mapped_cols = set(mapped_df.columns) if mapped_df is not None else set()
    roles: list[tuple[str, str]] = []
    for r in rule.required_roles:
        roles.append((r, "required"))
    for r in rule.optional_roles or []:
        if r not in rule.required_roles:
            roles.append((r, "optional"))
    seen: set[str] = set()
    out: list[MappingRow] = []
    for role, req in roles:
        if role in seen:
            continue
        seen.add(role)
        hay = haystack_tag(role)
        csv_col = csv_column_for_role(role, equipment_id, role_map)
        in_hist = role in mapped_cols
        out.append(
            MappingRow(
                role=role,
                haystack_tag=hay,
                csv_column=csv_col or "—",
                requirement=req,
                in_history=in_hist,
                present=in_hist,
            )
        )
    return out


def param_rows_for_rule(rule: CookbookRule, params: dict[str, Any] | None) -> list[ParamRow]:
    overrides = params or {}
    # Session may nest by rule id: { "VLV-1": { "confirm_min": 5 } }
    if rule.id in overrides and isinstance(overrides[rule.id], dict):
        overrides = overrides[rule.id]
    rows: list[ParamRow] = []
    for p in rule.params:
        raw = overrides.get(p.key, p.default) if isinstance(overrides, dict) else p.default
        try:
            val = float(raw)
        except (TypeError, ValueError):
            val = float(p.default)
        source = "override" if isinstance(overrides, dict) and p.key in overrides else "default"
        rows.append(
            ParamRow(
                key=p.key,
                label=p.label,
                unit=p.unit,
                value=val,
                default=float(p.default),
                source=source,
                min=float(p.min),
                max=float(p.max),
                step=float(p.step),
            )
        )
    return rows


def _status_and_meta(result: RuleResult | None) -> tuple[str, float | None, list[str], str, bool]:
    if result is None:
        return "NOT_RUN", None, [], "", False
    return (
        str(result.status),
        result.fault_hours,
        list(result.missing_roles or []),
        (result.notes or ""),
        True,
    )


def _is_plottable(result: RuleResult | None) -> bool:
    if result is None:
        return False
    if result.status in {
        "SKIPPED_MISSING_ROLES",
        "NOT_APPLICABLE_EQUIPMENT_TYPE",
        "ERROR",
        "SKIPPED_EQUIPMENT_OFF",
        "NOT_RUN",
    }:
        return False
    plot_series = getattr(result, "plot_series", None) or {}
    if isinstance(plot_series, dict) and plot_series:
        return True
    # FAULT/PASS still plottable via rule_result_chart when roles exist
    return result.status in {"FAULT", "PASS", "WARNING"}


def build_rule_card(
    *,
    equipment_id: str,
    rule: CookbookRule,
    result: RuleResult | None,
    role_map: dict,
    mapped_df: pd.DataFrame | None,
    params: dict[str, Any] | None = None,
    results: list | None = None,
    rcx_coverage: pd.DataFrame | None = None,
    weather: pd.DataFrame | None = None,
    has_sensor_fault_summary: bool | None = None,
) -> RuleCard:
    """Build shared card content for one cookbook rule on one device."""
    status, fault_hours, missing, notes, has_result = _status_and_meta(result)
    mrows = mapping_rows_for_rule(rule, equipment_id, role_map, mapped_df)
    req_total = sum(1 for m in mrows if m.requirement == "required")
    req_present = sum(1 for m in mrows if m.requirement == "required" and m.in_history)
    coverage = (100.0 * req_present / req_total) if req_total else None
    desc = (rule.summary or "").strip() or rule.title
    fields = catalog_fields(rule)
    related = analytics_related(rule.id)
    fit = data_model_fit(
        rule,
        equipment_id=equipment_id,
        role_map=role_map,
        mapped_df=mapped_df,
        results=results,
        rcx_coverage=rcx_coverage,
        weather=weather,
        has_sensor_fault_summary=has_sensor_fault_summary,
    )
    return RuleCard(
        rule_id=rule.id,
        title=rule.title,
        family=rule.family,
        equation=rule.equation or "",
        description=desc,
        status=status,
        fault_hours=fault_hours,
        missing_roles=missing,
        notes=notes,
        param_rows=param_rows_for_rule(rule, params),
        mapping_rows=mrows,
        required_roles_total=req_total,
        required_roles_present=req_present,
        coverage_pct=coverage,
        has_result=has_result,
        plottable=_is_plottable(result),
        equipment_kinds=list(fields.equipment_kinds),
        gate_mode=fields.gate_mode,
        confirm_seconds=fields.confirm_seconds,
        sensor_sweep=fields.sensor_sweep,
        control_output_sweep=fields.control_output_sweep,
        sweep_label=fields.sweep_label,
        plot_series=plot_series_bullets(rule),
        points_note=points_haystack_note(rule),
        analytics_hint=related.hint or analytics_hint(rule.id),
        analytics_fit=fit,
        rcx_preset_ids=related.rcx_preset_ids,
        catalog_facts=catalog_facts_pairs(rule),
    )


def equipment_mapping_coverage(
    rules: list[CookbookRule],
    equipment_id: str,
    role_map: dict,
    mapped_df: pd.DataFrame | None,
) -> tuple[int, int, float]:
    """Aggregate required-role coverage across applicable rules.

    Returns (present, total, pct). Roles counted once per unique required role
    across the rule set (union), so coverage reflects the device data model.
    """
    mapped_cols = set(mapped_df.columns) if mapped_df is not None else set()
    required: set[str] = set()
    for rule in rules:
        required.update(rule.required_roles)
    if not required:
        return 0, 0, 100.0
    present = sum(1 for r in required if r in mapped_cols)
    total = len(required)
    return present, total, 100.0 * present / total


def filter_status_bucket(status: str) -> str:
    """Map rule status to UI filter chip: FAULT / PASS / SKIPPED / Not run."""
    s = (status or "").upper()
    if s == "FAULT" or s == "WARNING":
        return "FAULT"
    if s == "PASS":
        return "PASS"
    if s in {"NOT_RUN", ""}:
        return "Not run"
    if s.startswith("SKIPPED") or s.startswith("NOT_APPLICABLE") or s == "ERROR":
        return "SKIPPED"
    return "SKIPPED"


PLACE_PLOT_HERE = (
    "[PLACE PLOT HERE — paste Plotly PNG from Streamlit camera or Trends]"
)

PLACE_RCX_PLOT_HERE = "[PLACE RCX PLOT HERE — {preset_id}]"
