"""Trend chart helpers — BRICK role resolution and fault overlays."""

from __future__ import annotations

from datetime import datetime
from typing import Any

ROLE_ALIASES: dict[str, list[str]] = {
    "supply_air_temperature": [
        "supply_air_temperature",
        "Supply_Air_Temperature",
        "SAT",
        "supply_air_temperature_sensor",
    ],
    "supply_air_temperature_setpoint": [
        "supply_air_temperature_setpoint",
        "Supply_Air_Temperature_Setpoint",
        "SAT_Setpoint",
        "sat_sp",
        "sat setpoint",
    ],
    "duct_static_pressure": [
        "duct_static_pressure",
        "Duct_Static_Pressure",
        "Supply_Air_Static_Pressure",
        "static_pressure",
        "SAP",
    ],
    "duct_static_pressure_setpoint": [
        "duct_static_pressure_setpoint",
        "Duct_Static_Setpoint",
        "static_sp",
        "static setpoint",
    ],
    "zone_temperature": [
        "zone_temperature",
        "Zone_Temperature",
        "Zone_Air_Temperature",
        "zone_temp",
        "zn-t",
        "AVG-ZN-T",
    ],
    "zone_cooling_setpoint": ["zone_cooling_setpoint", "Zone_Cooling_Setpoint", "cooling_sp"],
    "zone_heating_setpoint": ["zone_heating_setpoint", "Zone_Heating_Setpoint", "heating_sp"],
}


def historian_column_for_point(point: dict[str, Any]) -> str:
    """Feather/historian column — matches Edge ``plot_column_name``."""
    ext = str(point.get("external_id") or "").strip()
    if ext:
        return ext
    fdd = str(point.get("fdd_input") or "").strip()
    if fdd:
        return fdd
    pid = str(point.get("id") or "").strip()
    if pid:
        return pid
    return str(point.get("name") or "").strip()


def _role_matches(point: dict[str, Any], role: str) -> bool:
    candidates = {role.lower()}
    candidates.update(a.lower() for a in ROLE_ALIASES.get(role, []))
    hay = " ".join(
        str(point.get(k) or "")
        for k in ("brick_type", "role", "point_role", "semantic_role", "brick_tag", "name", "description", "fdd_input")
    ).lower().replace("-", "_").replace(" ", "_")
    for cand in candidates:
        if not cand:
            continue
        c = cand.replace("-", "_").replace(" ", "_")
        if c in hay or hay.find(c) >= 0:
            return True
    return False


def columns_for_roles(tree: dict[str, Any], roles: list[str]) -> list[str]:
    """Map BRICK roles to historian column names from model tree points."""
    points = tree.get("points") if isinstance(tree.get("points"), list) else []
    cols: list[str] = []
    for role in roles:
        for pt in points:
            if not isinstance(pt, dict) or not _role_matches(pt, role):
                continue
            col = historian_column_for_point(pt)
            if col and col not in cols:
                cols.append(col)
                break
    return cols


def resolve_roles_on_tree(tree: dict[str, Any], roles: list[str]) -> tuple[list[str], list[str]]:
    """Return (resolved columns, missing role names). Partial match allowed."""
    points = tree.get("points") if isinstance(tree.get("points"), list) else []
    cols: list[str] = []
    missing: list[str] = []
    for role in roles:
        found = False
        for pt in points:
            if not isinstance(pt, dict) or not _role_matches(pt, role):
                continue
            col = historian_column_for_point(pt)
            if col:
                cols.append(col)
                found = True
                break
        if not found:
            missing.append(role)
    return cols, missing


def canonical_roles_present(tree: dict[str, Any]) -> set[str]:
    """Roles that resolve to at least one historian column."""
    all_roles = set(ROLE_ALIASES.keys())
    for roles in (
        ["supply_air_temperature", "supply_air_temperature_setpoint"],
        ["duct_static_pressure", "duct_static_pressure_setpoint"],
        ["zone_temperature", "zone_cooling_setpoint", "zone_heating_setpoint"],
    ):
        all_roles.update(roles)
    present: set[str] = set()
    for role in all_roles:
        if columns_for_roles(tree, [role]):
            present.add(role)
    return present


def _parse_dt(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def fault_overlay_spans(
    timestamps: list[str],
    flags: list[int],
    *,
    label: str = "",
    severity: str = "warning",
) -> list[dict[str, Any]]:
    """Contiguous fault=1 regions as matplotlib axvspan specs (datetime x-axis)."""
    xs = [_parse_dt(t) for t in timestamps]
    spans: list[dict[str, Any]] = []
    start: datetime | None = None
    for i, flag in enumerate(flags):
        x = xs[i] if i < len(xs) else None
        if x is None:
            continue
        if flag:
            if start is None:
                start = x
        elif start is not None:
            spans.append({"x0": start, "x1": x, "label": label, "severity": severity})
            start = None
    if start is not None and xs:
        last = next((x for x in reversed(xs) if x is not None), None)
        if last is not None:
            spans.append({"x0": start, "x1": last, "label": label, "severity": severity})
    return spans


def overlays_from_readings(readings: dict[str, Any], *, show: bool = True) -> list[dict[str, Any]]:
    if not show:
        return []
    timestamps = readings.get("timestamps") or []
    fault_plots = readings.get("fault_plots") or {}
    panels = {str(p.get("key")): p for p in (readings.get("fault_panels") or []) if isinstance(p, dict)}
    out: list[dict[str, Any]] = []
    for key, flags in fault_plots.items():
        panel = panels.get(key) or {}
        spans = fault_overlay_spans(
            timestamps,
            flags,
            label=str(panel.get("title") or key),
            severity="warning",
        )
        out.extend(spans)
    return out


def render_trend_ax(
    ax,
    readings: dict[str, Any],
    *,
    title_cols: list[str] | None = None,
    overlays: list[dict[str, Any]] | None = None,
    overlay_fn=None,
) -> None:
    timestamps = readings.get("timestamps") or []
    series = readings.get("series") or {}
    labels = readings.get("labels") or {}
    xs = [datetime.fromisoformat(str(t).replace("Z", "+00:00")) for t in timestamps]

    for col, vals in series.items():
        label = str(labels.get(col) or col)
        ax.plot(xs, vals, label=label, linewidth=1.2)

    if overlays:
        colors = {
            "critical": (0.86, 0.15, 0.15, 0.25),
            "warning": (0.96, 0.62, 0.04, 0.22),
            "high": (0.95, 0.45, 0.1, 0.22),
            "medium": (0.98, 0.75, 0.15, 0.18),
            "info": (0.4, 0.5, 0.7, 0.15),
        }
        if overlay_fn:
            overlay_fn(ax, overlays)
        else:
            for ov in overlays:
                sev = str(ov.get("severity") or "warning").lower()
                color = colors.get(sev, colors["warning"])
                ax.axvspan(ov["x0"], ov["x1"], color=color, label=ov.get("label"))

    ax.set_xlabel("Time (UTC)")
    ax.legend(loc="upper right", fontsize=7)
    if title_cols:
        ax.set_ylabel(" / ".join(title_cols))
