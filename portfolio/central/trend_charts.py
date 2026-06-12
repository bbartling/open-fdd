"""Matplotlib trend charts from Edge /api/timeseries/readings (read-only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from portfolio.collector.edge_client import EdgeClient

ROLE_ALIASES: dict[str, list[str]] = {
    "supply_air_temperature": ["supply_air_temperature", "Supply_Air_Temperature", "SAT"],
    "supply_air_temperature_setpoint": [
        "supply_air_temperature_setpoint",
        "Supply_Air_Temperature_Setpoint",
        "SAT_Setpoint",
    ],
    "duct_static_pressure": ["duct_static_pressure", "Duct_Static_Pressure"],
    "duct_static_pressure_setpoint": ["duct_static_pressure_setpoint", "Duct_Static_Setpoint"],
    "zone_temperature": ["zone_temperature", "Zone_Temperature"],
    "zone_cooling_setpoint": ["zone_cooling_setpoint", "Zone_Cooling_Setpoint"],
    "zone_heating_setpoint": ["zone_heating_setpoint", "Zone_Heating_Setpoint"],
}


def _role_matches(point: dict[str, Any], role: str) -> bool:
    candidates = {role.lower()}
    candidates.update(a.lower() for a in ROLE_ALIASES.get(role, []))
    for key in ("brick_type", "role", "point_role", "semantic_role"):
        val = str(point.get(key) or "").strip().lower()
        if val in candidates or role.lower() in val:
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
            col = (
                pt.get("timeseries_column")
                or pt.get("historian_column")
                or pt.get("column")
                or pt.get("name")
            )
            if col and str(col) not in cols:
                cols.append(str(col))
                break
    return cols


def fetch_trend_readings(
    client: EdgeClient,
    *,
    site_id: str,
    columns: list[str],
    hours: int,
    token: str,
    include_faults: bool = True,
) -> dict[str, Any]:
    if not columns:
        return {}
    col_param = ",".join(columns)
    path = (
        f"/api/timeseries/readings?site_id={site_id}"
        f"&columns={col_param}&hours={hours}&include_faults={'true' if include_faults else 'false'}"
    )
    return client.api_get(path, token=token)


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
