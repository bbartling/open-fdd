"""Shared rule-plot catalog metadata for Plots UI, DOCX, and RULE_PLOT_CATALOG.md.

Source of truth for catalog-shaped fields (gates, plot series bullets, analytics hints,
Haystack rows). CookbookRule + RULE_GATES remain authoritative for rule math.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.column_map_json import COOKBOOK_TO_HAYSTACK_POINT
from app.rules.cookbook_catalog import CookbookRule
from app.rules.operational_gate import RULE_GATES

# Preferred Haystack names for roles missing from COOKBOOK_TO_HAYSTACK_POINT.
EXTENDED_HS: dict[str, str] = {
    "fan-speed-feedback": "fan-speed-feedback",
    "fan-current": "fan-current",
    "fan-power": "fan-power",
    "airflow-proof": "airflow-proof",
    "pump-status": "pump-status",
    "compressor-status": "compressor-status",
    "dx-stage": "dx-stage",
    "dx-cool-cmd": "dx-cool-cmd",
    "cool-stage": "cool-stage",
    "dx-cooling": "dx-cooling",
}

ANALYTICS_HINTS: dict[str, str] = {
    "SV-RANGE": "Plots sensor-fault summary stats when FAULT; Export sensor fault CSV.",
    "SV-FLATLINE": "Plots sensor-fault summary stats when FAULT.",
    "SV-SPIKE": "Plots sensor-fault summary stats when FAULT.",
    "SV-STALE": "Plots sensor-fault summary stats when FAULT.",
    "SV-RATE": "Profile table + rate evidence in metrics; thresholds are screening defaults.",
    "SCHED-1": "Overview occupancy calendar drives `occ_mode`; zone comfort band sliders (°F/°C display).",
    "SCHED-247": "Uses fan/pump status (or cmd fallback) across AHU and plant equipment.",
    "OAT-METEO": "Needs both BAS `oa_t` and web `wx_oa_t`; Prefer web OAT sidebar.",
    "ECON-3": "Web DB+DP free-cool band; Overview economizer_weather compliance hours; mech-cooling OAT bins are separate (DX/plant proof).",
    "ECON-6": "Winter min-OA damper vs web OAT < 25°F; Overview economizer_weather winter hours.",
    "ECON-7": "Economizer-OK band (web DP < 60°F, DB < 72°F) with cooling demand but damper not economizing; pairs with ECON-3 / MECH-OAT-1.",
    "MECH-OAT-1": "Proven DX/chiller cooling below 60°F web OAT; Overview prohibited_mech hours.",
    "CHW-NOLOAD-1": "Needs building zone or AHU-SAT satisfaction columns (batch inject); 30 min confirm.",
    "CW-OPT-1": "RCx `cw_reset_scatter` uses `cw_supply_t` vs web wet-bulb.",
    "CHW-1": "RCx `chw_reset_scatter` — CHW leave vs web OAT; motor weekly uses pump/status not leave-temp.",
    "CHW-2": "Plant motor weekly / chiller runtime — status/pump proof.",
    "AHU-DUCTHI": "RCx `duct_static_box` (fan-on) for static-reset opportunity.",
    "AHU-SATDEV": "RCx `ahu_sat_reset_scatter` — SAT vs web OAT.",
    "TRIM-1": "Duct static / pressure trim requests; related to duct-static box RCx.",
    "TRIM-3": "HW reset requests; RCx `hw_reset_scatter`.",
    "TRIM-4": "CHW reset requests; RCx `chw_reset_scatter`.",
    "VLV-1": "Valve closed + SAT vs SP **or** SAT vs MAT; fan gate when present.",
    "FC6": "Needs AHU `vav_total_flow` — empty plots often data gaps.",
    "ECON-1": "Needs OA damper / MAT / OAT roles (`oa_damper_pct` e.g. mad_c).",
    "ECON-2": "Needs OA damper / MAT / OAT roles.",
    "ECON-4": "Needs OA damper / MAT / OAT roles.",
    "ECON-5": "Needs heat/preheat roles.",
    "WX-1": "Weather family; web OAT enrich on weather frame.",
    "HP-1": "Mech-cooling OAT bins can use DX/compressor roles.",
}

DEFAULT_ANALYTICS_HINT = (
    "Fault hours / % on Results + FDD Plots card; RCx overlays only if roles match a preset."
)

# Rule id → RCx preset ids used when filling analytics in reports.
RCX_PRESETS_BY_RULE: dict[str, tuple[str, ...]] = {
    "AHU-SATDEV": ("ahu_sat_reset_scatter",),
    "AHU-DUCTHI": ("duct_static_box",),
    "TRIM-1": ("duct_static_box",),
    "TRIM-3": ("hw_reset_scatter",),
    "TRIM-4": ("chw_reset_scatter",),
    "CHW-1": ("chw_reset_scatter",),
    "CHW-2": ("chw_reset_scatter",),
    "CW-OPT-1": ("cw_reset_scatter",),
    "VAV-1": ("zone_comfort_rank", "zone_temps"),
    "SCHED-1": ("zone_comfort_rank",),
}


@dataclass(frozen=True)
class CatalogFields:
    family: str
    equipment_kinds: list[str]
    gate_mode: str
    confirm_seconds: float
    sensor_sweep: bool
    control_output_sweep: bool
    sweep_label: str


@dataclass(frozen=True)
class HaystackRoleRow:
    role: str
    haystack_tag: str
    requirement: str  # required | optional


@dataclass
class AnalyticsRelated:
    hint: str
    rcx_preset_ids: tuple[str, ...] = ()
    fit_lines: list[str] = field(default_factory=list)


def haystack_tag(role: str) -> str:
    if role in COOKBOOK_TO_HAYSTACK_POINT:
        return COOKBOOK_TO_HAYSTACK_POINT[role]
    if role in EXTENDED_HS:
        return EXTENDED_HS[role]
    return role.replace("_", "-")


def gate_mode_label(rule_id: str) -> str:
    gate = RULE_GATES.get(rule_id)
    if gate is None:
        return "—"
    label = str(gate.kind)
    if gate.startup_delay_seconds:
        label += f" (startup {gate.startup_delay_seconds:g}s)"
    return label


def sweep_label(rule: CookbookRule) -> str:
    flags: list[str] = []
    if rule.sensor_sweep:
        flags.append("sensor_sweep")
    if rule.control_output_sweep:
        flags.append("control_output_sweep")
    return ", ".join(flags) if flags else "—"


def catalog_fields(rule: CookbookRule) -> CatalogFields:
    return CatalogFields(
        family=rule.family,
        equipment_kinds=list(rule.equipment_kinds),
        gate_mode=gate_mode_label(rule.id),
        confirm_seconds=float(rule.confirm_seconds),
        sensor_sweep=bool(rule.sensor_sweep),
        control_output_sweep=bool(rule.control_output_sweep),
        sweep_label=sweep_label(rule),
    )


def haystack_rows(rule: CookbookRule) -> list[HaystackRoleRow]:
    rows: list[HaystackRoleRow] = []
    seen: set[str] = set()
    for role in rule.required_roles:
        if role in seen:
            continue
        seen.add(role)
        rows.append(HaystackRoleRow(role, haystack_tag(role), "required"))
    for role in rule.optional_roles or []:
        if role in seen:
            continue
        seen.add(role)
        rows.append(HaystackRoleRow(role, haystack_tag(role), "optional"))
    return rows


def points_haystack_note(rule: CookbookRule) -> str:
    if rule.sensor_sweep or rule.control_output_sweep:
        return (
            "Sweep rule: plots sensors / control outputs present on the equipment "
            "(see sweep role lists in cookbook_catalog.py). No fixed required-role list."
        )
    if not rule.required_roles and not (rule.optional_roles or []):
        return "No fixed roles."
    return ""


def plot_series_bullets(rule: CookbookRule) -> list[str]:
    bullets: list[str] = []
    plot_roles = list(rule.required_roles) + [
        x for x in (rule.optional_roles or []) if x not in rule.required_roles
    ]
    if rule.sensor_sweep:
        bullets.append("Present sweep sensors (temps / statuses on mapped frame)")
    elif rule.control_output_sweep:
        bullets.append("Present 0–100% control outputs (dampers / valves / fan cmds)")
    elif plot_roles:
        for role in plot_roles:
            bullets.append(f"{role} → {haystack_tag(role)}")
    else:
        bullets.append("Chart falls back to common roles present (sat, zone_t, …) if any")
    bullets.append("confirmed_fault swim lane (bool shade) when the rule was run")
    return bullets


def analytics_hint(rule_id: str) -> str:
    return ANALYTICS_HINTS.get(rule_id) or DEFAULT_ANALYTICS_HINT


def analytics_related(rule_id: str) -> AnalyticsRelated:
    return AnalyticsRelated(
        hint=analytics_hint(rule_id),
        rcx_preset_ids=RCX_PRESETS_BY_RULE.get(rule_id, ()),
    )


def data_model_fit(
    rule: CookbookRule,
    *,
    equipment_id: str | None = None,
    role_map: dict | None = None,
    mapped_df: pd.DataFrame | None = None,
    results: list | None = None,
    rcx_coverage: pd.DataFrame | None = None,
    weather: pd.DataFrame | None = None,
    has_sensor_fault_summary: bool | None = None,
) -> list[str]:
    """Short human-readable fit lines for Plots / DOCX analytics section."""
    lines: list[str] = []
    related = analytics_related(rule.id)

    if rule.sensor_sweep or rule.id.startswith("SV-"):
        if has_sensor_fault_summary is True:
            lines.append("Sensor fault summary: available (FAULT sensors on this device)")
        elif has_sensor_fault_summary is False:
            lines.append("Sensor fault summary: not fit — no FAULT sensor-validation rows yet")
        elif results is not None and equipment_id:
            fault_sv = any(
                getattr(r, "equipment_id", None) == equipment_id
                and str(getattr(r, "rule_id", "")).startswith("SV-")
                and str(getattr(r, "status", "")) == "FAULT"
                for r in results
            )
            if fault_sv:
                lines.append("Sensor fault summary: available (FAULT sensors on this device)")
            else:
                lines.append("Sensor fault summary: not fit — no FAULT sensor-validation rows yet")

    if mapped_df is not None and not (rule.sensor_sweep or rule.control_output_sweep):
        missing = [r for r in rule.required_roles if r not in mapped_df.columns]
        if missing:
            lines.append(f"Required roles missing on frame: {', '.join(missing)}")
        elif rule.required_roles:
            lines.append(
                f"Required roles mapped: {len(rule.required_roles)}/{len(rule.required_roles)}"
            )

    if weather is not None and not weather.empty:
        if "web-outside-air-temp" in weather.columns or any(
            c for c in weather.columns if "temp" in str(c).lower()
        ):
            lines.append("Weather / web OAT: loaded")
    elif rule.id in {"OAT-METEO", "CW-OPT-1", "AHU-SATDEV", "CHW-1", "TRIM-3", "TRIM-4"}:
        lines.append("Weather / web OAT: not loaded — reset scatters may be empty")

    if rcx_coverage is not None and not rcx_coverage.empty and related.rcx_preset_ids:
        by_id = {
            str(row.preset_id): row
            for row in rcx_coverage.itertuples()
            if hasattr(row, "preset_id")
        }
        for pid in related.rcx_preset_ids:
            row = by_id.get(pid)
            if row is None:
                lines.append(f"RCx `{pid}`: not in coverage table")
                continue
            n = int(getattr(row, "series_count", 0) or 0)
            rc = int(getattr(row, "row_count", 0) or 0)
            if rc > 0:
                lines.append(f"RCx `{pid}`: fit — {n} series / {rc} rows")
            else:
                reason = str(getattr(row, "empty_reason", "") or "no data")
                lines.append(f"RCx `{pid}`: not fit — {reason}")

    if not lines and related.hint:
        lines.append("See analytics hint above")
    return lines


def catalog_facts_pairs(rule: CookbookRule) -> list[tuple[str, str]]:
    """Field/value pairs matching RULE_PLOT_CATALOG.md."""
    fields = catalog_fields(rule)
    return [
        ("Family", fields.family),
        ("Equipment kinds", ", ".join(fields.equipment_kinds)),
        ("Operational gate", fields.gate_mode),
        ("Default confirm", f"{fields.confirm_seconds:g}s"),
        ("Sweep", fields.sweep_label),
    ]
