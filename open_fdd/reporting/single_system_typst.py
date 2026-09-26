"""Offline single-system (and building-folder) AHU FDD/RCx Typst pack.

This path reads a device folder (``history_wide.csv`` + ``column_map.json``),
filters to one calendar month, runs the pandas oracle, and writes Typst
sources whose figures come from the same Plotly helpers as the Railway UI.

It does **not** replace the sacred BUILDING_100 Overview-mirrored lab PDF.

Scopes:

* ``single-system`` — one AHU device folder (v1 demo shape, e.g. ``AHU_1``).
* ``building`` — a parent folder whose children are device folders. AHU blocks
  are reported; other equipment is listed as skipped.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from open_fdd.analytics.anomaly.detectors import median_sample_delta
from open_fdd.analytics.anomaly.io import iter_ahu_io_points, load_device_folder
from open_fdd.analytics.anomaly.plots import point_slug
from open_fdd.rules.cookbook_catalog import SENSOR_LIMITS

ANOMALY_NOTE = "These screening notes are not equipment faults."

_MIN_FAN_ON_SAMPLES = 6

_PLAIN_ROLE = {
    "outside-air-temp": "outdoor air temperature",
    "web-outside-air-temp": "web outdoor air temperature",
    "mixed-air-temp": "mixed air temperature",
    "return-air-temp": "return air temperature",
    "discharge-air-temp": "supply air temperature",
    "duct-static-pressure": "duct static pressure",
    "duct-static-pressure-sp": "duct static setpoint",
    "outside-air-damper": "outdoor air damper",
    "fan-cmd": "fan speed command",
    "fan-status": "fan status",
    "cooling-valve": "cooling valve",
    "heating-valve": "heating valve",
}

_SV_PLAIN = {
    "SV-RANGE": "reading out of physical range",
    "SV-FLATLINE": "sensor stuck flat",
    "SV-SPIKE": "reading jumped suddenly",
    "SV-STALE": "readings stopped updating",
    "SV-RATE": "reading changed faster than expected",
}

_BOUNDARY = (
    "Offline report from mapped roles and history. The same PDF is produced from a "
    "device folder, an Open-FDD server, or a future vendor adapter. "
    "This is not the BUILDING_100 Overview-mirrored lab PDF."
)

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


@dataclass
class SingleSystemReport:
    typ_path: Path
    summary_path: Path
    pdf_path: Path | None = None
    devices: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


def device_folders(root: Path | str, scope: str) -> list[Path]:
    """Resolve device folders for ``single-system`` or ``building`` scope."""
    if scope not in {"single-system", "building"}:
        raise ValueError("scope must be single-system or building")
    folder = Path(root)
    if (folder / "history_wide.csv").is_file():
        return [folder]
    if scope == "single-system":
        raise FileNotFoundError(
            f"{folder} has no history_wide.csv; pass an AHU device folder or --scope building"
        )
    if not folder.is_dir():
        raise FileNotFoundError(f"missing building folder {folder}")
    children = [
        child
        for child in sorted(folder.iterdir())
        if child.is_dir()
        and (child / "history_wide.csv").is_file()
        and (child / "column_map.json").is_file()
    ]
    if not children:
        raise FileNotFoundError(f"no device folders under {folder}")
    return children


def equipment_label(column_map: dict[str, Any], folder: Path) -> str:
    equip = column_map.get("equip")
    if isinstance(equip, str) and equip.strip():
        return equip.strip()
    device = column_map.get("device")
    if isinstance(device, str) and device.strip():
        return device.strip()
    return folder.name


def role_frame(device) -> pd.DataFrame:
    """Rename mapped CSV columns to Haystack role names for the pandas oracle."""
    frame = pd.DataFrame(index=device.frame.index)
    for role, column in device.points:
        if column not in device.frame.columns:
            continue
        frame[role] = pd.to_numeric(device.frame[column], errors="coerce")
    label = equipment_label(device.column_map, Path("AHU"))
    frame.attrs["equipment_id"] = label
    equip_type = device.column_map.get("equipType") or device.column_map.get("equipment_type") or "ahu"
    frame.attrs["equipment_type"] = str(equip_type)
    return frame


def parse_report_month(value: str) -> str:
    """Return a validated ``YYYY-MM`` label."""
    text = (value or "").strip()
    if not _MONTH_RE.match(text):
        raise ValueError("month must be YYYY-MM")
    return text


def dominant_month(index: pd.DatetimeIndex) -> str:
    """Calendar month (UTC) with the most samples."""
    if index is None or len(index) == 0:
        raise ValueError("history has no timestamps")
    stamps = index.tz_convert("UTC") if index.tz is not None else index.tz_localize("UTC")
    labels = pd.Series(stamps.strftime("%Y-%m"))
    return str(labels.mode().iloc[0])


def filter_to_month(frame: pd.DataFrame, month: str) -> pd.DataFrame:
    """Keep rows whose UTC timestamp falls in ``YYYY-MM``."""
    label = parse_report_month(month)
    start = pd.Timestamp(f"{label}-01", tz="UTC")
    end = start + pd.DateOffset(months=1)
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("role frame index must be timestamps")
    stamps = frame.index.tz_convert("UTC") if frame.index.tz is not None else frame.index.tz_localize("UTC")
    mask = (stamps >= start) & (stamps < end)
    out = frame.loc[mask].copy()
    out.attrs = dict(frame.attrs)
    if out.empty:
        raise ValueError(f"no samples in {label}")
    return out


def load_web_oat_csv(path: Path | str) -> pd.DataFrame:
    """Read a sidecar weather CSV (``timestamp_utc`` plus a dry-bulb column).

    Accepts ``web-outside-air-temp`` or Open-Meteo ``web_oa_t``. A 15-minute
    file is normalized here; ``attach_web_oat`` reindexes it onto the BAS clock.
    """
    from open_fdd.analytics.weather_psychrometrics import enrich_weather_frame

    raw = pd.read_csv(path)
    if "timestamp_utc" not in raw.columns:
        raise ValueError(f"{path} needs a timestamp_utc column")
    raw["timestamp_utc"] = pd.to_datetime(raw["timestamp_utc"], utc=True, format="mixed")
    frame = enrich_weather_frame(raw.set_index("timestamp_utc").sort_index())
    for column in frame.columns:
        if pd.api.types.is_numeric_dtype(frame[column]) or column.startswith("web-"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def attach_web_oat(
    frame: pd.DataFrame,
    *,
    web_oat: str | Path | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> tuple[pd.DataFrame, str | None]:
    """Join web outdoor-air temperature without overwriting BAS ``outside-air-temp``.

    Sources, in order: a mapped ``web-outside-air-temp`` column, a CSV path, or
    ``web_oat="fetch"`` (Open-Meteo via ``--lat`` / ``--lon``). CSV aliases
    include ``web_oa_t``. ``align_to_index`` puts a 15-minute file onto the
    BAS timestamps, then ``merge_weather`` / ``weather_resolver`` keeps web
    OAT primary (``prefer_web_oat``).
    """
    from open_fdd.analytics.weather_psychrometrics import prefer_web_oat
    from open_fdd.rules.runner import merge_weather

    if "web-outside-air-temp" in frame.columns and frame["web-outside-air-temp"].notna().any():
        return merge_weather(frame, None), "column"
    if web_oat is None or str(web_oat).strip() == "":
        return merge_weather(frame, None), None

    from open_fdd.analytics.open_meteo import align_to_index

    token = str(web_oat).strip()
    if token == "fetch":
        if lat is None or lon is None:
            raise ValueError("web OAT fetch requires lat and lon")
        from open_fdd.analytics.open_meteo import fetch_open_meteo

        weather = fetch_open_meteo(float(lat), float(lon), frame.index.min(), frame.index.max())
        source = "open-meteo"
    else:
        path = Path(token)
        if not path.is_file():
            raise FileNotFoundError(f"web OAT file not found: {path}")
        weather = load_web_oat_csv(path)
        source = "csv"
    aligned = align_to_index(weather, frame.index)
    joined = merge_weather(frame, aligned)
    if "web-outside-air-temp" not in joined.columns or not joined["web-outside-air-temp"].notna().any():
        raise ValueError("web OAT join produced no web-outside-air-temp values")
    preferred = prefer_web_oat(joined, aligned, prefer_web=True)
    if preferred is not None:
        joined["oa_t_effective"] = preferred
        joined.attrs["oa_t_effective_source"] = "web"
    return joined, source


def data_health_rows(role_df: pd.DataFrame, points: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Coverage and physical-bound checks. These are quality flags, not FDD faults."""
    n = int(len(role_df))
    rows: list[dict[str, Any]] = []
    for role, column in points:
        if role not in role_df.columns:
            continue
        series = pd.to_numeric(role_df[role], errors="coerce")
        present = int(series.notna().sum())
        limits = SENSOR_LIMITS.get(role)
        out_of_range = 0
        bound = ""
        if limits and present:
            out_of_range = int(((series < float(limits["lo"])) | (series > float(limits["hi"]))).fillna(False).sum())
            bound = f"{float(limits['lo']):g}..{float(limits['hi']):g}"
        rows.append(
            {
                "role": role,
                "column": column,
                "samples": n,
                "coverage_pct": round(100.0 * present / n, 1) if n else 0.0,
                "min": None if present == 0 else round(float(series.min()), 1),
                "max": None if present == 0 else round(float(series.max()), 1),
                "out_of_range": out_of_range,
                "bound": bound,
            }
        )
    return rows


def fan_on_fraction(role_df: pd.DataFrame) -> float | None:
    """Share of samples with fan status (else command) at or above 0.5."""
    if "fan-status" in role_df.columns:
        series = pd.to_numeric(role_df["fan-status"], errors="coerce")
    elif "fan-cmd" in role_df.columns:
        series = pd.to_numeric(role_df["fan-cmd"], errors="coerce")
        series = series.where(series <= 1.0, series / 100.0)
    else:
        return None
    if int(series.notna().sum()) == 0:
        return None
    return round(float((series.fillna(0) >= 0.5).mean()), 3)


def representative_week(frame: pd.DataFrame, week_start: str | None = None) -> tuple[pd.DataFrame, str]:
    """Seven-day window inside ``frame``.

    ``week_start`` (``YYYY-MM-DD``, UTC) pins the window. The April OptiPlex
    example is ``2026-04-06`` (through 2026-04-12). Without it, the window
    with the most fan-on samples is used.
    """
    if frame.empty:
        return frame, ""
    if week_start:
        start = pd.Timestamp(week_start)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        else:
            start = start.tz_convert("UTC")
        end = start + pd.Timedelta(days=7)
        window = frame.loc[(frame.index >= start) & (frame.index < end)].copy()
        if window.empty:
            raise ValueError(f"no samples in the week starting {start:%Y-%m-%d}")
        window.attrs = dict(frame.attrs)
        label = f"{window.index.min():%Y-%m-%d} to {window.index.max():%Y-%m-%d} UTC"
        return window, label
    fan = _fan_on_mask(frame)
    start0 = frame.index.min().floor("D")
    last = frame.index.max()
    best = frame
    best_on = -1
    cursor = start0
    while cursor <= last:
        end = cursor + pd.Timedelta(days=7)
        window = frame.loc[(frame.index >= cursor) & (frame.index < end)]
        if not window.empty:
            on = int(fan.reindex(window.index).fillna(False).sum()) if fan is not None else int(len(window))
            if on > best_on:
                best_on = on
                best = window.copy()
                best.attrs = dict(frame.attrs)
        cursor += pd.Timedelta(days=1)
    label = f"{best.index.min():%Y-%m-%d} to {best.index.max():%Y-%m-%d} UTC"
    return best, label


def _fan_on_mask(frame: pd.DataFrame) -> pd.Series | None:
    for role in ("fan-status", "fan-cmd"):
        if role not in frame.columns or not frame[role].notna().any():
            continue
        num = pd.to_numeric(frame[role], errors="coerce")
        scaled = num.where(num <= 1.5, num / 100.0)
        return scaled.fillna(0) > 0.05
    return None


def _one_decimal(value: float) -> str:
    return f"{float(value):.1f}"


def _confirmed_fault(result) -> bool:
    if getattr(result, "status", "") != "FAULT":
        return False
    hours = getattr(result, "fault_hours", None)
    if hours is None or float(hours) <= 0:
        return False
    fault = getattr(result, "confirmed_fault", None)
    if fault is None:
        return False
    return bool(pd.Series(fault).fillna(False).astype(bool).any())


def _identity_pack(frame: pd.DataFrame, equipment_id: str) -> tuple[dict[str, pd.DataFrame], dict]:
    raw = frame.copy()
    raw.attrs["equipment_type"] = raw.attrs.get("equipment_type") or "AHU"
    raw.attrs["equipment_id"] = equipment_id
    role_map = {equipment_id: {column: column for column in frame.columns}}
    return {equipment_id: raw}, role_map


def _write_plotly_png(figure, path: Path) -> bool:
    try:
        height = int(getattr(figure.layout, "height", None) or 480)
        figure.write_image(str(path), scale=2, width=980, height=max(360, height))
    except Exception:
        return False
    return path.is_file() and path.stat().st_size > 100


def _pyplot():
    import matplotlib

    if "agg" not in matplotlib.get_backend().lower():
        matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    return plt


def _mpl_from_plotly(figure, path: Path) -> bool:
    """Export Plotly traces when Kaleido is unavailable. Axes stay those of the figure."""
    traces = list(getattr(figure, "data", []) or [])
    if not traces:
        return False
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(9.0, 4.2))
    ax2 = None
    for trace in traces:
        kind = str(getattr(trace, "type", "") or "")
        ys = list(getattr(trace, "y", []) or [])
        if kind == "box" and ys:
            name = str(getattr(trace, "name", "") or "")
            try:
                ax.boxplot([ys], tick_labels=[name or "series"])
            except TypeError:
                ax.boxplot([ys], labels=[name or "series"])
            continue
        xs = list(getattr(trace, "x", []) or [])
        if not xs or not ys:
            continue
        target = ax
        if getattr(trace, "yaxis", None) not in {None, "y"}:
            if ax2 is None:
                ax2 = ax.twinx()
            target = ax2
        target.plot(xs, ys, lw=1.2, label=str(getattr(trace, "name", "") or ""))
    title = ""
    if figure.layout.title and figure.layout.title.text:
        title = str(figure.layout.title.text)
    ax.set_title(title)
    if figure.layout.xaxis and figure.layout.xaxis.title and figure.layout.xaxis.title.text:
        ax.set_xlabel(str(figure.layout.xaxis.title.text))
    if figure.layout.yaxis and figure.layout.yaxis.title and figure.layout.yaxis.title.text:
        ax.set_ylabel(str(figure.layout.yaxis.title.text))
    if figure.layout.xaxis and figure.layout.xaxis.range:
        ax.set_xlim(list(figure.layout.xaxis.range))
    if figure.layout.yaxis and figure.layout.yaxis.range:
        ax.set_ylim(list(figure.layout.yaxis.range))
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path.is_file() and path.stat().st_size > 100


def _write_figure_png(figure, path: Path) -> bool:
    if figure is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if _write_plotly_png(figure, path):
        return True
    return _mpl_from_plotly(figure, path)


# Engineer-facing note under the section-6 scatter. Axes stay
# x = OAT−RAT (delta_or_f), y = MAT−RAT (delta_mr_f), bottom-left viewport.
def econ_scatter_caption(temp_unit: str = "°F") -> str:
    """Section-6 note. ``temp_unit`` follows the series units (°F or °C)."""
    return (
    "Outdoor-air mixing with the supply fan on. "
    "The horizontal axis is outdoor-air temperature minus return-air temperature (OAT − RAT). "
    "The vertical axis is mixed-air temperature minus return-air temperature (MAT − RAT). "
    "The view is the bottom-left diagnostic quadrant only, where outdoor air is at or below return air "
    "and mixed air is at or below return air. "
    "A sample is plotted only when the fan is on and the absolute difference between outdoor air and return air "
    f"is at least 10{temp_unit}, so the outdoor-air fraction is identifiable.\n\n"
    "Dotted reference lines are the outdoor-air fraction that would put mixed air on that line: "
    "0%, 25%, 50%, 75%, and 100% outdoor air. "
    "When an outdoor-air damper is mapped, point color is damper position from closed (0%) to open (100%). "
    "In theory, points at a given outdoor-air fraction lie near the matching fraction line. "
    "A high damper position (yellow, near fully open) should cluster on the 100% outdoor-air line. "
    "Intermediate colors should sit near their own fraction lines.\n\n"
    "Damper percent is actuator position. It is not the calculated fresh-air fraction, and it is not an airflow fraction.\n\n"
    "Points off their fraction line indicate a mixing problem, a temperature-sensor error, "
    "or the wrong outdoor-air volume (too much or too little outdoor air).\n\n"
    "The plot is clearest in extreme cold or hot outdoor weather, when outdoor air and return air are far apart. "
    "In mild economizer weather, where mixed air, return air, and outdoor air are nearly the same temperature, "
    "the differences shrink and those errors are hardest to see."
)


def write_econ_scatter(role_df: pd.DataFrame, path: Path, *, temp_unit: str = "°F") -> bool:
    """Write ``economizer_delta_scatter`` clipped to the bottom-left mixing quadrant.

    x = OAT−RAT (``delta_or_f``), y = MAT−RAT (``delta_mr_f``). Axis limits
    stop at 0 so quadrants with OAT>RAT or MAT>RAT are outside the viewport.
    """
    from open_fdd.analytics.charts import economizer_delta_scatter
    from open_fdd.analytics.core import ECON_DIAG_DT_MIN_F, build_economizer_delta_points

    equipment_id = str(role_df.attrs.get("equipment_id") or "AHU")
    points = build_economizer_delta_points(
        role_df,
        equipment_id=equipment_id,
        dt_min_f=ECON_DIAG_DT_MIN_F,
    )
    figure = economizer_delta_scatter(
        points,
        dt_min_f=ECON_DIAG_DT_MIN_F,
        viewport="bottom_left",
        temp_unit=temp_unit,
    )
    return _write_figure_png(figure, path)


def _mapped_roles(frame: pd.DataFrame) -> set[str]:
    roles: set[str] = set()
    for column in frame.columns:
        series = pd.to_numeric(frame[column], errors="coerce")
        if series.notna().any():
            roles.add(str(column))
    return roles


def _figure_for_spec(spec, week: pd.DataFrame, equipment_id: str, units_map: dict[str, str] | None = None):
    """Draw one profile figure with the shared Plotly helpers."""
    from open_fdd.analytics.charts import (
        bas_vs_web_oat_overlay,
        economizer_temps_overlay,
        multi_equipment_box,
        multi_equipment_timeseries,
        oat_scatter,
    )
    from open_fdd.analytics.core import build_economizer_delta_points
    from open_fdd.analytics.rcx_plots import collect_oat_scatter, collect_role_series
    from open_fdd.analytics.units import resolve_role_unit

    units_map = units_map or {}
    temp_unit = str(units_map.get("outside-air-temp") or "°F")
    static_unit = str(units_map.get("duct-static-pressure") or "in. w.c.")
    frames, role_map = _identity_pack(week, equipment_id)
    if spec.kind == "econ_temps":
        points = build_economizer_delta_points(week, equipment_id=equipment_id)
        if "discharge-air-temp" in week.columns and not points.empty:
            points = points.copy()
            points["sat_f"] = pd.to_numeric(week["discharge-air-temp"], errors="coerce").reindex(points.index)
        return economizer_temps_overlay(
            points,
            equipment_id=equipment_id,
            full_index=week.index,
            temp_unit=temp_unit,
        )
    if spec.kind == "bas_web":
        return bas_vs_web_oat_overlay(frames, role_map, temp_unit=temp_unit)
    if spec.kind == "oat_scatter":
        long_df = collect_oat_scatter(
            frames,
            role_map,
            y_role=spec.y_role or "discharge-air-temp",
            weather=None,
            equipment_types=("AHU",),
            operating_on=True,
        )
        if long_df is None or long_df.empty:
            return None
        return oat_scatter(
            long_df,
            title=spec.title,
            x_title=f"Web outdoor air {temp_unit}",
            y_title=resolve_role_unit(spec.y_role or "discharge-air-temp", units_map) or f"Supply air {temp_unit}",
        )
    if spec.kind == "box":
        series_map = collect_role_series(
            frames,
            role_map,
            role=spec.y_role or "duct-static-pressure",
            equipment_types=("AHU",),
            filter_fan_on=True,
        )
        return multi_equipment_box(
            series_map,
            title=spec.title,
            y_title=resolve_role_unit(spec.y_role or "duct-static-pressure", units_map) or static_unit,
        )
    if spec.kind == "timeseries":
        series_map = collect_role_series(
            frames,
            role_map,
            role=spec.y_role,
            equipment_types=("AHU",),
            filter_fan_on=spec.fan_on,
        )
        if spec.overlay_role:
            extra = collect_role_series(
                frames,
                role_map,
                role=spec.overlay_role,
                equipment_types=("AHU",),
                filter_fan_on=spec.fan_on,
            )
            for eq_id, series in extra.items():
                series_map[f"{eq_id} setpoint"] = series
        return multi_equipment_timeseries(
            series_map,
            title=spec.title,
            y_title=resolve_role_unit(spec.y_role, units_map) or spec.y_role,
        )
    return None


def _rcx_week_figures(
    week: pd.DataFrame,
    equipment_id: str,
    out_dir: Path,
    slug: str,
    *,
    profile_id: str,
    units_map: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    from open_fdd.reporting.report_template import select_figures

    figures: list[dict[str, str]] = []
    for spec in select_figures(profile_id, _mapped_roles(week)):
        figure = _figure_for_spec(spec, week, equipment_id, units_map)
        name = f"figures/{slug}_rcx_{spec.id}.png"
        if figure is not None and _write_figure_png(figure, out_dir / name):
            figures.append(
                {
                    "id": spec.id,
                    "title": spec.title,
                    "caption": spec.caption,
                    "path": name,
                }
            )
    return figures


def _plain_role(role: str) -> str:
    return _PLAIN_ROLE.get(role, str(role).replace("-", " "))


def _month_phrase(month: str) -> str:
    return pd.Timestamp(f"{month}-01").strftime("%B %Y")


def _is_sv_rule(rule_id: str) -> bool:
    return str(rule_id).startswith("SV-")


def _faulted_roles(result) -> list[str]:
    metrics = getattr(result, "metrics", None) or {}
    roles: list[str] = []
    for key in ("sv_sweep_evidence", "sv_rate_evidence"):
        for row in metrics.get(key) or []:
            if not isinstance(row, dict) or not row.get("role"):
                continue
            hours = row.get("fault_hours", row.get("fault_hours_raw"))
            try:
                flagged = bool(row.get("faulted")) or float(hours or 0) > 0
            except (TypeError, ValueError):
                flagged = bool(row.get("faulted"))
            if flagged:
                roles.append(str(row["role"]))
    seen: list[str] = []
    for role in roles:
        if role not in seen:
            seen.append(role)
    return seen


def sensor_validation_bullets(results, health: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Plain pass/fail lines for sensor-validation rules. Findings only, unless clean."""
    checked = [result for result in results if _is_sv_rule(result.rule_id)]
    findings = [result for result in checked if _confirmed_fault(result)]
    if not findings:
        if not checked or all(str(result.status).startswith("SKIPPED") for result in checked):
            return [
                {
                    "outcome": "skipped",
                    "text": "Sensor checks skipped — no mapped sensors to review.",
                }
            ]
        return [
            {
                "outcome": "pass",
                "text": "Passed. No stuck sensors, out-of-range readings, or stale data.",
            }
        ]
    health_by_role = {row["role"]: row for row in health}
    bullets: list[dict[str, Any]] = []
    for result in findings:
        issue = _SV_PLAIN.get(result.rule_id, "sensor check failed")
        roles = _faulted_roles(result)
        if result.rule_id == "SV-RANGE" and roles:
            for role in roles:
                label = _plain_role(role).capitalize()
                bound = health_by_role.get(role) or {}
                low = high = None
                if bound.get("max") is not None:
                    low = _one_decimal(bound["min"])
                    high = _one_decimal(bound["max"])
                bullets.append(
                    {
                        "outcome": "fail",
                        "rule_id": result.rule_id,
                        "roles": [role],
                        "labels": [label],
                        "low": low,
                        "high": high,
                        "text": f"{label}: {issue}.",
                    }
                )
            continue
        labels = [_plain_role(role).capitalize() for role in roles]
        bullets.append(
            {
                "outcome": "fail",
                "rule_id": result.rule_id,
                "roles": roles,
                "labels": labels,
                "text": f"{'; '.join(labels) or 'A mapped sensor'}: {issue}.",
            }
        )
    return bullets


def anomaly_plain_checklist(
    frame: pd.DataFrame,
    points: list[tuple[str, str]],
    month: str,
) -> list[dict[str, str]]:
    """High-level pass/fail lines. No method names and no plot files."""
    from open_fdd.analytics.anomaly.detectors import (
        is_binary_like,
        rolling_mad_flags,
        rolling_zscore_flags,
        samples_per_day,
    )

    fan = _fan_on_mask(frame)
    fan_on = int(fan.fillna(False).sum()) if fan is not None else int(len(frame))
    if fan is not None and fan_on < _MIN_FAN_ON_SAMPLES:
        return [
            {
                "outcome": "skipped",
                "text": "Skipped — not enough fan-on data.",
            }
        ]
    window = samples_per_day(frame.index)
    when = _month_phrase(month)
    bullets: list[dict[str, str]] = []
    for role, _column in points:
        if role not in frame.columns:
            continue
        series = pd.to_numeric(frame[role], errors="coerce")
        if is_binary_like(series):
            continue
        view = series.where(fan) if fan is not None else series
        usable = int(view.dropna().shape[0])
        label = _plain_role(role).capitalize()
        if usable < max(8, window // 2):
            bullets.append(
                {
                    "outcome": "skipped",
                    "role": role,
                    "labels": [label],
                    "text": f"{label}: skipped — not enough fan-on data.",
                }
            )
            continue
        flags = rolling_zscore_flags(view, window=window) | rolling_mad_flags(view, window=window)
        if not bool(flags.fillna(False).any()):
            bullets.append(
                {
                    "outcome": "looks_normal",
                    "role": role,
                    "labels": [label],
                    "text": f"{label}: looks normal.",
                }
            )
            continue
        detail = _unusual_sentence(label, view, flags, when)
        bullets.append(
            {
                "outcome": "needs_a_look",
                "role": role,
                "labels": [label],
                "detail": detail,
                "text": f"{label}: needs a look. {detail}",
            }
        )
    if not bullets:
        return [
            {
                "outcome": "skipped",
                "text": "Skipped — mapped points do not vary enough to screen.",
            }
        ]
    return bullets


def _unusual_sentence(label: str, series: pd.Series, flags: pd.Series, when: str) -> str:
    """One everyday sentence about the flagged samples. Not an equipment diagnosis."""
    mask = flags.reindex(series.index).fillna(False).astype(bool)
    flagged = pd.to_numeric(series, errors="coerce").where(mask).dropna()
    rest = pd.to_numeric(series, errors="coerce").where(~mask).dropna()
    if flagged.empty:
        return f"{label} looked unusual in {when}."
    low = float(flagged.min())
    high = float(flagged.max())
    typical = float(rest.median()) if not rest.empty else float(pd.to_numeric(series, errors="coerce").median())
    if low <= 1.0 and typical > 20:
        return f"{label} had sudden dropouts near zero in {when}."
    if high >= typical + 30:
        return f"{label} jumped to {_one_decimal(high)}, well above the rest of {when}."
    if low <= typical - 30:
        return f"{label} dropped to {_one_decimal(low)}, well below the rest of {when}."
    return (
        f"{label} moved unusually in {when} "
        f"(about {_one_decimal(low)} to {_one_decimal(high)})."
    )


def _fault_seen(result, frame: pd.DataFrame, month: str) -> str:
    """Plain description of the confirmed fault window. Not the equation."""
    from open_fdd.rules import RULES_BY_ID
    from open_fdd.rules.evidence import sparse_intervals

    hours = _one_decimal(float(result.fault_hours or 0.0))
    when = _month_phrase(month)
    mask = getattr(result, "confirmed_fault", None)
    if mask is None:
        return f"{hours} hours in {when} met this condition."
    aligned = mask.reindex(frame.index).fillna(False).astype(bool)
    if not bool(aligned.any()):
        return f"{hours} hours in {when} met this condition."
    intervals = sparse_intervals(aligned)
    start = pd.Timestamp(intervals[0]["first"])
    end = pd.Timestamp(intervals[-1]["last"])
    window = f"{start:%Y-%m-%d %H:%M} UTC through {end:%Y-%m-%d %H:%M} UTC"
    rule = RULES_BY_ID.get(result.rule_id)
    roles: list[str] = []
    if rule is not None:
        roles = list(rule.required_roles) + list(getattr(rule, "optional_roles", []) or [])
    bits: list[str] = []
    for role in roles:
        if role not in frame.columns:
            continue
        series = pd.to_numeric(frame[role], errors="coerce").where(aligned).dropna()
        if series.empty:
            continue
        label = _plain_role(role)
        if int(series.nunique()) <= 3 and float(series.max()) <= 1.5:
            on_pct = 100.0 * float((series >= 0.5).mean())
            bits.append(f"{label} was on for {_one_decimal(on_pct)} percent of those samples")
        else:
            bits.append(f"{label} was about {_one_decimal(float(series.median()))}")
        if len(bits) >= 4:
            break
    sentence = f"In {when} this holds for {hours} hours, {window}."
    if bits:
        sentence += " " + "; ".join(bits) + "."
    return sentence


def _fault_figures(
    frame: pd.DataFrame,
    results,
    out_dir: Path,
    slug: str,
    month: str,
    units_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    from open_fdd.analytics.charts import rule_result_chart
    from open_fdd.reporting.rule_meta import DUCT_STATIC_RULE_IDS, rule_title, rule_troubleshoot
    from open_fdd.rules import RULES_BY_ID

    rows: list[dict[str, Any]] = []
    for result in results:
        if _is_sv_rule(result.rule_id) or not _confirmed_fault(result):
            continue
        rule = RULES_BY_ID.get(result.rule_id)
        roles = None
        if rule is not None:
            roles = list(rule.required_roles) + list(getattr(rule, "optional_roles", []) or [])
        figure = rule_result_chart(
            frame,
            result,
            required_roles=roles,
            units_map=units_map,
            pressure_and_fan_only=result.rule_id in DUCT_STATIC_RULE_IDS,
        )
        name = f"figures/{slug}_fault_{point_slug(result.rule_id)}.png"
        path = name if figure is not None and _write_figure_png(figure, out_dir / name) else ""
        hours = round(float(result.fault_hours or 0.0), 1)
        rows.append(
            {
                "rule_id": result.rule_id,
                "title": rule_title(result.rule_id),
                "troubleshoot": rule_troubleshoot(result.rule_id),
                "seen": _fault_seen(result, frame, month),
                "fault_hours": hours,
                "figure": path,
            }
        )
    return rows


def _executive_summary(
    *,
    label: str,
    month: str,
    frame: pd.DataFrame,
    sensor_checks: list[dict[str, Any]],
    anomaly: list[dict[str, Any]],
    faults: list[dict[str, Any]],
    web_source: str | None,
) -> str:
    from open_fdd.reporting.narrative_polish import (
        polish_anomaly_paragraph,
        polish_executive_summary,
        polish_sensor_paragraph,
    )

    poll = _poll_seconds(frame.index)
    span_h = _one_decimal((len(frame) * poll) / 3600.0)
    fan = fan_on_fraction(frame)
    fan_pct = _one_decimal(100.0 * fan) if fan is not None else None
    return polish_executive_summary(
        label=label,
        month_phrase=_month_phrase(month),
        sample_count=len(frame),
        span_h=span_h,
        sensor_paragraph=polish_sensor_paragraph(sensor_checks),
        anomaly_paragraph=polish_anomaly_paragraph(anomaly),
        anomaly_note=ANOMALY_NOTE,
        faults=faults,
        web_source=web_source,
        fan_on_percent=fan_pct,
    )


def _code_raw(value: object) -> str:
    text = "" if value is None else str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'raw("{escaped}")'


def _markup_raw(value: object) -> str:
    return "#" + _code_raw(value)


def _ai_note(device: dict[str, Any], slot: str) -> list[str]:
    text = str((device.get("ai_comments") or {}).get(slot) or "").strip()
    if not text:
        return []
    return [_markup_raw(text), ""]


def _device_typst(device: dict[str, Any]) -> str:
    parts = [
        f"== {_markup_raw(device['equipment_id'])}",
        "",
        "=== Sensor checks",
        "",
        "Checks for stuck, out-of-range, or stale sensors. Only failed checks are listed when something is wrong.",
        "",
    ]
    parts.extend([_markup_raw(device.get("sensor_narrative") or ""), ""])
    parts.extend(_ai_note(device, "sensor_checks"))
    parts.extend(
        [
            "=== Anomaly screening",
            "",
            "A quick look at whether each varying trend is ordinary this month. Not an equipment fault list.",
            "",
        ]
    )
    parts.extend([_markup_raw(device.get("anomaly_narrative") or ""), ""])
    parts.extend(_ai_note(device, "anomaly_screening"))
    parts.extend(
        [
            "=== Executive summary",
            "",
            _markup_raw(device["executive_summary"]),
            "",
        ]
    )
    parts.extend(_ai_note(device, "executive_summary"))
    parts.extend(
        [
            f"=== RCx week ({_markup_raw(device['week'])})",
            "",
            "One week inside the filtered month. Figures follow the mapped roles for this system profile.",
            "",
        ]
    )
    parts.extend(_ai_note(device, "rcx_week"))
    if not device.get("rcx"):
        if device.get("profile_implemented"):
            parts.extend(["No mapped roles for this profile's figures in this week.", ""])
        else:
            parts.extend(
                [
                    _markup_raw(
                        f"{device.get('profile_label') or 'This system'} is a registered profile. "
                        "Figures for it are not drawn yet."
                    ),
                    "",
                ]
            )
    for figure in device.get("rcx") or []:
        parts.extend(
            [
                _markup_raw(figure["title"]),
                "",
                _markup_raw(figure["caption"]),
                "",
                f'#image("{figure["path"]}", width: 100%)',
                "",
            ]
        )
    parts.extend(
        [
            "=== Confirmed faults",
            "",
            "A figure is included only when the cookbook rule has confirmed fault hours in the filtered month.",
            "",
        ]
    )
    parts.extend(_ai_note(device, "confirmed_faults"))
    if not device.get("faults"):
        parts.extend(["No confirmed cookbook faults in this month.", ""])
    for fault in device.get("faults") or []:
        parts.extend(
            [
                f"==== {_markup_raw(fault['rule_id'] + ' — ' + fault['title'])}",
                "",
                _markup_raw("Troubleshoot: " + fault["troubleshoot"]),
                "",
                _markup_raw("In the data: " + fault["seen"]),
                "",
            ]
        )
        if fault.get("figure"):
            parts.extend([f'#image("{fault["figure"]}", width: 100%)', ""])
    parts.extend(["=== Economizer delta scatter", ""])
    parts.extend(_ai_note(device, "economizer"))
    if device.get("scatter_figure"):
        parts.extend([f'#image("{device["scatter_figure"]}", width: 80%)', ""])
    else:
        parts.extend(
            [
                "Scatter unavailable: need at least five fan-on samples in the bottom-left quadrant with |OAT-RAT| >= 10 F.",
                "",
            ]
        )
    parts.extend([device.get("scatter_caption") or econ_scatter_caption(), ""])
    return "\n".join(parts)


def render_typst(summary: dict[str, Any]) -> str:
    skipped = summary.get("skipped") or []
    skip_line = ""
    if skipped:
        names = ", ".join(item["folder"] for item in skipped)
        skip_line = _markup_raw(f"Skipped (no AHU IO): {names}") + "\n\n"
    body = "\n".join(_device_typst(device) for device in summary["devices"])
    month = summary.get("month") or ""
    return "\n".join(
        [
            "#set page(paper: \"us-letter\", margin: 0.7in)",
            "#set text(size: 11pt)",
            f"= AHU screening ({summary['scope']}, {month})",
            "",
            _markup_raw(_BOUNDARY),
            "",
            skip_line.rstrip(),
            body,
        ]
    )


def _is_ahu_folder(folder: Path) -> bool:
    column_map = json.loads((folder / "column_map.json").read_text(encoding="utf-8"))
    if not isinstance(column_map, dict):
        return False
    return bool(iter_ahu_io_points(column_map))


def _poll_seconds(index: pd.DatetimeIndex) -> float:
    delta = median_sample_delta(index)
    seconds = float(delta.total_seconds())
    if seconds <= 0:
        return 300.0
    return seconds


def _one_device(
    folder: Path,
    out_dir: Path,
    *,
    month: str,
    web_oat: str | Path | None,
    lat: float | None,
    lon: float | None,
    week: str | None = None,
    profile: str | None = None,
    ai_comments: dict[str, str] | None = None,
) -> dict[str, Any]:
    from open_fdd.reporting.report_template import DeviceFolderSource, load_ai_comments, resolve_profile
    from open_fdd.rules import run_all

    from open_fdd.analytics.units import stamp_display_units
    from open_fdd.reporting.narrative_polish import polish_anomaly_paragraph, polish_sensor_paragraph

    history = DeviceFolderSource(folder).load()
    label = history.equipment_id
    framed = history.frame
    framed.attrs["equipment_id"] = label
    column_map_path = Path(folder) / "column_map.json"
    column_map = json.loads(column_map_path.read_text(encoding="utf-8")) if column_map_path.is_file() else {}
    units_map = stamp_display_units(framed, column_map if isinstance(column_map, dict) else {})
    temp_unit = str(units_map.get("outside-air-temp") or "°F")
    framed = filter_to_month(framed, month)
    framed, web_source = attach_web_oat(framed, web_oat=web_oat, lat=lat, lon=lon)
    framed.attrs["equipment_id"] = label
    chosen = resolve_profile(profile, history.equipment_type)
    comments = load_ai_comments(folder, ai_comments)

    slug = point_slug(label)
    health = data_health_rows(framed, history.points)
    results = run_all(framed, poll_seconds=_poll_seconds(framed.index))
    sensor_checks = sensor_validation_bullets(results, health)
    anomaly = anomaly_plain_checklist(framed, history.points, month)
    sensor_narrative = polish_sensor_paragraph(sensor_checks)
    anomaly_narrative = polish_anomaly_paragraph(anomaly)
    faults = _fault_figures(framed, results, out_dir, slug, month, units_map)
    week, week_label = representative_week(framed, week_start=week)
    framed.attrs["units_map"] = units_map
    week.attrs["units_map"] = units_map
    rcx = _rcx_week_figures(week, label, out_dir, slug, profile_id=chosen.id, units_map=units_map)
    scatter_name = f"figures/{slug}_econ_scatter.png"
    scatter_ok = write_econ_scatter(framed, out_dir / scatter_name, temp_unit=temp_unit)
    summary_text = _executive_summary(
        label=label,
        month=month,
        frame=framed,
        sensor_checks=sensor_checks,
        anomaly=anomaly,
        faults=faults,
        web_source=web_source,
    )
    return {
        "equipment_id": label,
        "folder": str(folder),
        "month": month,
        "week": week_label,
        "web_oat_source": web_source,
        "profile": chosen.id,
        "profile_label": chosen.label,
        "profile_implemented": chosen.implemented,
        "source_id": history.source_id,
        "ai_comments": comments,
        "unit_system": str(framed.attrs.get("unit_system") or "imperial"),
        "executive_summary": summary_text,
        "sensor_narrative": sensor_narrative,
        "anomaly_narrative": anomaly_narrative,
        "scatter_caption": econ_scatter_caption(temp_unit),
        "sensor_checks": sensor_checks,
        "anomaly": anomaly,
        "health": health,
        "faults": faults,
        "rcx": rcx,
        "scatter_figure": scatter_name if scatter_ok else "",
    }


def compile_typst(typ_path: Path) -> Path:
    """Compile ``report.typ`` to ``report.pdf`` beside it.

    This is the PDF step inside ``open-fdd-anomaly report --compile``. It runs
    ``typst compile`` when that binary is on ``PATH``.
    """
    binary = shutil.which("typst")
    if not binary:
        raise FileNotFoundError(
            "typst is not on PATH. Install the typst binary, then re-run "
            "open-fdd-anomaly report with --compile. Typst sources are already in "
            f"{typ_path.parent}."
        )
    pdf_path = typ_path.with_suffix(".pdf")
    completed = subprocess.run(
        [binary, "compile", typ_path.name, pdf_path.name],
        cwd=typ_path.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "typst compile failed").strip()
        raise ValueError(detail)
    return pdf_path


def build_single_system_report(
    folder: Path | str,
    out_dir: Path | str,
    *,
    scope: str = "single-system",
    month: str | None = None,
    web_oat: str | Path | None = None,
    lat: float | None = None,
    lon: float | None = None,
    week: str | None = None,
    profile: str | None = None,
    ai_comments: dict[str, str] | None = None,
    top_n: int = 5,
    max_days: int = 10,
    methods: list[str] | None = None,
    command: str | None = None,
    compile_pdf: bool = False,
) -> SingleSystemReport:
    """Write ``report.typ``, ``report_summary.json``, and Plotly PNGs under ``out_dir``.

    ``compile_pdf=True`` (CLI ``--compile``) also writes ``report.pdf`` when
    ``typst`` is on ``PATH``. ``top_n``, ``max_days``, and ``methods`` belong to
    ``open-fdd-anomaly screen``. This report does not emit anomaly histograms
    or day-zoom galleries.
    """
    del top_n, max_days, methods, command
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    folders = device_folders(folder, scope)
    if month is None:
        probe = load_device_folder(folders[0])
        month = dominant_month(probe.frame.index)
    month = parse_report_month(month)
    devices: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for child in folders:
        if not _is_ahu_folder(child):
            skipped.append({"folder": child.name, "reason": "no AHU IO in column_map"})
            continue
        devices.append(
            _one_device(
                child,
                destination,
                month=month,
                web_oat=web_oat,
                lat=lat,
                lon=lon,
                week=week,
                profile=profile,
                ai_comments=ai_comments,
            )
        )
    if not devices:
        raise ValueError(f"no AHU device folders to report under {folder}")
    from open_fdd.reporting.report_template import AI_COMMENT_SLOTS, HISTORY_SOURCES, PROFILES

    summary = {
        "scope": scope,
        "month": month,
        "boundary": _BOUNDARY,
        "ai_comment_slots": list(AI_COMMENT_SLOTS),
        "profiles": [
            {"id": item.id, "label": item.label, "implemented": item.implemented}
            for item in PROFILES.values()
        ],
        "history_sources": sorted(HISTORY_SOURCES),
        "devices": devices,
        "skipped": skipped,
    }
    typ_path = destination / "report.typ"
    typ_path.write_text(render_typst(summary), encoding="utf-8")
    summary_path = destination / "report_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    pdf_path = None
    if compile_pdf:
        pdf_path = compile_typst(typ_path)
    return SingleSystemReport(
        typ_path=typ_path,
        summary_path=summary_path,
        pdf_path=pdf_path,
        devices=[item["equipment_id"] for item in devices],
        skipped=skipped,
    )
