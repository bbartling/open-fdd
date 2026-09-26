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

ANOMALY_NOTE = "Unsupervised anomaly minutes are not confirmed FDD faults."

_BOUNDARY = (
    "Offline pandas-oracle pack for one AHU folder or a building folder of device "
    "subfolders. This is not the BUILDING_100 Overview-mirrored lab PDF. "
    "Figures use the PyPI Plotly helpers shared with the Railway UI."
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
    """Read a sidecar weather CSV (``timestamp_utc`` plus a dry-bulb column)."""
    raw = pd.read_csv(path)
    if "timestamp_utc" not in raw.columns:
        raise ValueError(f"{path} needs a timestamp_utc column")
    raw["timestamp_utc"] = pd.to_datetime(raw["timestamp_utc"], utc=True, format="mixed")
    return raw.set_index("timestamp_utc").sort_index()


def attach_web_oat(
    frame: pd.DataFrame,
    *,
    web_oat: str | Path | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> tuple[pd.DataFrame, str | None]:
    """Join web outdoor-air temperature without overwriting BAS ``outside-air-temp``.

    Sources, in order: a mapped ``web-outside-air-temp`` column, a CSV path, or
    ``web_oat="fetch"`` (Open-Meteo via ``--lat`` / ``--lon``).
    """
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


def representative_week(frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Seven-day window inside ``frame`` with the most fan-on samples."""
    if frame.empty:
        return frame, ""
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
        xs = list(getattr(trace, "x", []) or [])
        ys = list(getattr(trace, "y", []) or [])
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


def write_econ_scatter(role_df: pd.DataFrame, path: Path) -> bool:
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
    )
    return _write_figure_png(figure, path)


def _rcx_week_figures(
    week: pd.DataFrame,
    equipment_id: str,
    out_dir: Path,
    slug: str,
) -> list[dict[str, str]]:
    from open_fdd.analytics.charts import (
        bas_vs_web_oat_overlay,
        economizer_temps_overlay,
        multi_equipment_timeseries,
    )
    from open_fdd.analytics.core import build_economizer_delta_points
    from open_fdd.analytics.rcx_plots import PRESETS, collect_role_series
    from open_fdd.analytics.units import resolve_role_unit

    frames, role_map = _identity_pack(week, equipment_id)
    figures: list[dict[str, str]] = []
    for preset in PRESETS:
        if preset.family != "AHU / air" or preset.chart != "timeseries":
            continue
        series_map = collect_role_series(
            frames,
            role_map,
            role=preset.role,
            equipment_types=preset.equipment_types,
        )
        if preset.overlay_role:
            extra = collect_role_series(
                frames,
                role_map,
                role=preset.overlay_role,
                equipment_types=preset.equipment_types,
            )
            for eq_id, series in extra.items():
                series_map[f"{eq_id} setpoint"] = series
        if not series_map:
            continue
        figure = multi_equipment_timeseries(
            series_map,
            title=preset.title,
            y_title=resolve_role_unit(preset.role) or preset.role,
        )
        name = f"figures/{slug}_rcx_{preset.id}.png"
        if figure is not None and _write_figure_png(figure, out_dir / name):
            figures.append(
                {
                    "id": preset.id,
                    "title": preset.title,
                    "caption": preset.description,
                    "path": name,
                }
            )

    points = build_economizer_delta_points(week, equipment_id=equipment_id)
    overlay = economizer_temps_overlay(points, equipment_id=equipment_id)
    overlay_name = f"figures/{slug}_rcx_econ_temps.png"
    if overlay is not None and _write_figure_png(overlay, out_dir / overlay_name):
        figures.append(
            {
                "id": "econ_temps",
                "title": "Free-cooling temps + OA damper",
                "caption": "OAT, RAT, MAT, and SAT on the temperature axis; OA damper percent on the right axis.",
                "path": overlay_name,
            }
        )
    bas_web = bas_vs_web_oat_overlay(frames, role_map)
    bas_name = f"figures/{slug}_rcx_bas_web_oat.png"
    if bas_web is not None and _write_figure_png(bas_web, out_dir / bas_name):
        figures.append(
            {
                "id": "bas_web_oat",
                "title": "BAS vs web outdoor-air temperature",
                "caption": "BAS outside-air-temp and web-outside-air-temp on one temperature axis.",
                "path": bas_name,
            }
        )
    return figures


def _fault_figures(
    frame: pd.DataFrame,
    out_dir: Path,
    slug: str,
    month: str,
) -> list[dict[str, Any]]:
    from open_fdd.analytics.charts import rule_result_chart
    from open_fdd.reporting.rule_meta import rule_summary, rule_title
    from open_fdd.rules import RULES_BY_ID, run_all

    poll = _poll_seconds(frame.index)
    rows: list[dict[str, Any]] = []
    for result in run_all(frame, poll_seconds=poll):
        if not _confirmed_fault(result):
            continue
        rule = RULES_BY_ID.get(result.rule_id)
        roles = None
        if rule is not None:
            roles = list(rule.required_roles) + list(getattr(rule, "optional_roles", []) or [])
        figure = rule_result_chart(frame, result, required_roles=roles)
        name = f"figures/{slug}_fault_{point_slug(result.rule_id)}.png"
        path = name if figure is not None and _write_figure_png(figure, out_dir / name) else ""
        hours = round(float(result.fault_hours or 0.0), 1)
        note = (result.notes or "").strip()
        data = f"{_one_decimal(hours)} fault hours in {month}."
        if note:
            data = f"{data} {note}"
        rows.append(
            {
                "rule_id": result.rule_id,
                "title": rule_title(result.rule_id),
                "summary": rule_summary(result.rule_id),
                "data": data,
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
    health: list[dict[str, Any]],
    faults: list[dict[str, Any]],
    web_source: str | None,
) -> str:
    poll = _poll_seconds(frame.index)
    span_h = round((len(frame) * poll) / 3600.0, 1)
    issues = []
    for row in health:
        if not row.get("out_of_range"):
            continue
        issues.append(
            f"{row['role']} has {int(row['out_of_range'])} sample(s) outside {row['bound']} "
            f"(min {_one_decimal(row['min'])}, max {_one_decimal(row['max'])})"
        )
    parts = [
        f"{label} in {month}: {len(frame)} samples, {_one_decimal(span_h)} h.",
    ]
    if issues:
        parts.append("Data issues: " + "; ".join(issues) + ".")
    else:
        parts.append("Mapped roles stay inside cookbook physical bounds.")
    if faults:
        bits = [f"{row['rule_id']} {_one_decimal(row['fault_hours'])} h" for row in faults]
        parts.append("Confirmed faults: " + ", ".join(bits) + ".")
    else:
        parts.append("No confirmed cookbook faults in this month.")
    if web_source:
        parts.append(f"Web outdoor-air temperature joined from {web_source}.")
    else:
        parts.append("No web outdoor-air temperature was joined, so rules that require it stay skipped.")
    fan = fan_on_fraction(frame)
    if fan is not None:
        parts.append(f"Fan is ON for {_one_decimal(100.0 * fan)} percent of samples.")
    parts.append(ANOMALY_NOTE)
    return " ".join(parts)


def _code_raw(value: object) -> str:
    text = "" if value is None else str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'raw("{escaped}")'


def _markup_raw(value: object) -> str:
    return "#" + _code_raw(value)


def _device_typst(device: dict[str, Any]) -> str:
    parts = [
        f"== {_markup_raw(device['equipment_id'])}",
        "",
        "=== Executive summary",
        "",
        _markup_raw(device["executive_summary"]),
        "",
        f"=== RCx week ({_markup_raw(device['week'])})",
        "",
        "One representative week inside the filtered month, preferring fan-ON coverage. "
        "Lines use the PyPI Plotly helpers shared with Railway RCx plots.",
        "",
    ]
    if not device.get("rcx"):
        parts.extend(["No AHU timeseries presets had mapped roles in this week.", ""])
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
    if not device.get("faults"):
        parts.extend(["No confirmed cookbook faults in this month.", ""])
    for fault in device.get("faults") or []:
        parts.extend(
            [
                f"==== {_markup_raw(fault['rule_id'] + ' — ' + fault['title'])}",
                "",
                _markup_raw("Rule: " + fault["summary"]),
                "",
                _markup_raw("Data: " + fault["data"]),
                "",
            ]
        )
        if fault.get("figure"):
            parts.extend([f'#image("{fault["figure"]}", width: 100%)', ""])
    parts.extend(
        [
            "=== Economizer delta scatter",
            "",
            _markup_raw(
                "economizer_delta_scatter: x = OAT - RAT (delta_or_f), "
                "y = MAT - RAT (delta_mr_f). Reference lines y = OA fraction * x "
                "for 0/25/50/75/100% OA. Fan ON and |OAT-RAT| >= 10 F. "
                "Viewport is the bottom-left mixing quadrant only (both deltas <= 0: OAT <= RAT and MAT <= RAT). "
                "Do not plot OAT-MAT vs RAT-MAT."
            ),
            "",
        ]
    )
    if device.get("scatter_figure"):
        parts.extend([f'#image("{device["scatter_figure"]}", width: 80%)', ""])
    else:
        parts.extend(
            [
                "Scatter unavailable: need at least five fan-on samples in the bottom-left quadrant with |OAT-RAT| >= 10 F.",
                "",
            ]
        )
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
) -> dict[str, Any]:
    device = load_device_folder(folder)
    label = equipment_label(device.column_map, folder)
    framed = role_frame(device)
    framed.attrs["equipment_id"] = label
    framed = filter_to_month(framed, month)
    framed, web_source = attach_web_oat(framed, web_oat=web_oat, lat=lat, lon=lon)
    framed.attrs["equipment_id"] = label
    slug = point_slug(label)
    health = data_health_rows(framed, device.points)
    faults = _fault_figures(framed, out_dir, slug, month)
    week, week_label = representative_week(framed)
    rcx = _rcx_week_figures(week, label, out_dir, slug)
    scatter_name = f"figures/{slug}_econ_scatter.png"
    scatter_ok = write_econ_scatter(framed, out_dir / scatter_name)
    summary_text = _executive_summary(
        label=label,
        month=month,
        frame=framed,
        health=health,
        faults=faults,
        web_source=web_source,
    )
    return {
        "equipment_id": label,
        "folder": str(folder),
        "month": month,
        "week": week_label,
        "web_oat_source": web_source,
        "executive_summary": summary_text,
        "health": health,
        "faults": faults,
        "rcx": rcx,
        "scatter_figure": scatter_name if scatter_ok else "",
    }


def compile_typst(typ_path: Path) -> Path:
    """Compile ``report.typ`` beside itself. Raises if ``typst`` is missing."""
    binary = shutil.which("typst")
    if not binary:
        raise FileNotFoundError(
            "typst is not on PATH. Install typst and run: "
            f"typst compile {typ_path.name} {typ_path.with_suffix('.pdf').name}"
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
    top_n: int = 5,
    max_days: int = 10,
    methods: list[str] | None = None,
    command: str | None = None,
    compile_pdf: bool = False,
) -> SingleSystemReport:
    """Write ``report.typ``, ``report_summary.json``, and Plotly PNGs under ``out_dir``.

    ``top_n``, ``max_days``, and ``methods`` belong to ``open-fdd-anomaly screen``.
    This report does not emit anomaly histograms or day-zoom galleries.
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
            )
        )
    if not devices:
        raise ValueError(f"no AHU device folders to report under {folder}")
    summary = {
        "scope": scope,
        "month": month,
        "boundary": _BOUNDARY,
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
