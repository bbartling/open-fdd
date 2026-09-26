"""Offline single-system (and building-folder) AHU FDD/RCx Typst pack.

This path reads a device folder (``history_wide.csv`` + ``column_map.json``),
runs the pandas oracle, and writes Typst sources. It does **not** replace the
sacred BUILDING_100 Overview-mirrored lab PDF.

Scopes:

* ``single-system`` — one AHU device folder (v1 demo shape, e.g. ``AHU_1``).
* ``building`` — a parent folder whose children are device folders. AHU blocks
  are reported; other equipment is listed as skipped. The full-building
  Overview mirror for BUILDING_100 stays on the external legacy kit.
"""

from __future__ import annotations

import json
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

SV_RULE_IDS = ("SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE")
FC1_RULE_IDS = ("FC1",)
ECON_RULE_IDS = ("FC2", "FC3", "FC10", "FC11", "ECON-1", "ECON-2", "ECON-4")

ANOMALY_NOTE = (
    "Unsupervised anomaly minutes are not FDD faults. "
    "Z-score and MAD are SQL-portable screens; STL and Isolation Forest are Python-only. "
    "Cookbook FC1 and economizer rules apply a fan-ON operational gate. "
    "Do not read the scoreboard as confirmed faults."
)

_BOUNDARY = (
    "Offline pandas-oracle pack for one AHU folder or a building folder of device "
    "subfolders. This is not the BUILDING_100 Overview-mirrored lab PDF."
)


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


def rule_rows(role_df: pd.DataFrame, rule_ids: tuple[str, ...], poll_seconds: float) -> list[dict[str, Any]]:
    from open_fdd.rules import run_rule

    rows: list[dict[str, Any]] = []
    for rule_id in rule_ids:
        try:
            result = run_rule(rule_id, role_df, poll_seconds=poll_seconds)
        except Exception as exc:
            rows.append(
                {
                    "rule_id": rule_id,
                    "status": "ERROR",
                    "fault_hours": None,
                    "missing_roles": [],
                    "notes": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        hours = result.fault_hours
        rows.append(
            {
                "rule_id": result.rule_id,
                "status": result.status,
                "fault_hours": None if hours is None else round(float(hours), 1),
                "missing_roles": list(result.missing_roles),
                "notes": result.notes,
            }
        )
    return rows


def _pyplot():
    import matplotlib

    if "agg" not in matplotlib.get_backend().lower():
        matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    return plt


def write_fc1_figure(role_df: pd.DataFrame, path: Path) -> bool:
    """Duct static and setpoint on the left axis; fan command percent on the right."""
    if "duct-static-pressure" not in role_df.columns:
        return False
    plt = _pyplot()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9.0, 3.6))
    x = role_df.index
    ax.plot(x, role_df["duct-static-pressure"], color="#2563eb", lw=1.3, label="duct static")
    if "duct-static-pressure-sp" in role_df.columns:
        ax.plot(x, role_df["duct-static-pressure-sp"], color="#ea580c", lw=1.1, label="static SP")
    ax.set_ylabel("in. w.c.")
    ax.grid(axis="y", alpha=0.3)
    if "fan-cmd" in role_df.columns:
        ax2 = ax.twinx()
        cmd = pd.to_numeric(role_df["fan-cmd"], errors="coerce")
        pct = cmd.where(cmd > 1.0, cmd * 100.0)
        ax2.plot(x, pct, color="#16a34a", lw=1.0, alpha=0.85, label="fan cmd %")
        ax2.set_ylabel("Fan command (%)")
        ax2.set_ylim(-5, 105)
    ax.set_title("FC1 evidence — duct static vs setpoint (fan % on the right axis)")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True


def write_econ_scatter(role_df: pd.DataFrame, path: Path) -> bool:
    """Write ``economizer_delta_scatter``: x = OAT−RAT, y = MAT−RAT.

    Points come from ``build_economizer_delta_points`` (``delta_or_f`` /
    ``delta_mr_f`` only). Reference lines are y = OA fraction × x. Fan-off
    rows and samples with |OAT−RAT| < 10°F are not the plotted cloud.
    """
    from open_fdd.analytics.charts import economizer_delta_scatter
    from open_fdd.analytics.core import ECON_DIAG_DT_MIN_F, build_economizer_delta_points

    equipment_id = str(role_df.attrs.get("equipment_id") or "AHU")
    points = build_economizer_delta_points(
        role_df,
        equipment_id=equipment_id,
        dt_min_f=ECON_DIAG_DT_MIN_F,
    )
    figure = economizer_delta_scatter(points, dt_min_f=ECON_DIAG_DT_MIN_F)
    if figure is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if _write_plotly_png(figure, path):
        return True
    return _write_delta_scatter_png(points, path, dt_min_f=ECON_DIAG_DT_MIN_F)


def _write_plotly_png(figure, path: Path) -> bool:
    """Static export of the Plotly ``economizer_delta_scatter`` figure."""
    try:
        figure.write_image(str(path), scale=2, width=900, height=480)
    except Exception:
        return False
    return path.is_file() and path.stat().st_size > 100


def _write_delta_scatter_png(points: pd.DataFrame, path: Path, *, dt_min_f: float) -> bool:
    """Matplotlib fallback that plots only ``delta_or_f`` / ``delta_mr_f``."""
    df = points
    if "identifiable" in df.columns:
        df = df[df["identifiable"].astype(bool)]
    df = df.dropna(subset=["delta_or_f", "delta_mr_f"])
    if len(df) < 5:
        return False
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    x_lo = float(df["delta_or_f"].min())
    x_hi = float(df["delta_or_f"].max())
    if x_lo == x_hi:
        x_lo, x_hi = x_lo - 1.0, x_hi + 1.0
    xs = [x_lo, x_hi]
    for frac, label in ((0.0, "0% OA"), (0.25, "25%"), (0.5, "50%"), (0.75, "75%"), (1.0, "100% OA")):
        ax.plot(xs, [frac * x_lo, frac * x_hi], color="#94a3b8", lw=0.8, ls=":", label=label)
    ax.scatter(df["delta_or_f"], df["delta_mr_f"], s=18, color="#2563eb", alpha=0.8, zorder=3)
    ax.set_xlabel("OAT − RAT (°F)")
    ax.set_ylabel("MAT − RAT (°F)")
    ax.set_title(f"Economizer free-cooling delta scatter (fan on, |OAT−RAT|≥{dt_min_f:.0f}°F)")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path.is_file() and path.stat().st_size > 100


def _code_raw(value: object) -> str:
    """Typst ``raw`` call for use inside a code-mode function argument list."""
    text = "" if value is None else str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'raw("{escaped}")'


def _markup_raw(value: object) -> str:
    """Typst ``#raw`` for a markup-mode paragraph or heading."""
    return "#" + _code_raw(value)


def _table(headers: list[str], rows: list[list[object]]) -> str:
    cells = ", ".join(_code_raw(header) for header in headers)
    lines = [f"#table(columns: {len(headers)}, inset: 4pt, stroke: 0.4pt,", f"  table.header({cells}),"]
    for row in rows:
        lines.append("  " + ", ".join(_code_raw(cell) for cell in row) + ",")
    lines.append(")")
    return "\n".join(lines)


def _rule_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        missing = ", ".join(row.get("missing_roles") or [])
        hours = row.get("fault_hours")
        body.append(
            [
                row.get("rule_id"),
                row.get("status"),
                "" if hours is None else hours,
                missing,
            ]
        )
    return _table(["rule", "status", "fault_h", "missing roles"], body)


def _health_table(rows: list[dict[str, Any]]) -> str:
    body = [
        [
            row["role"],
            row["coverage_pct"],
            row["min"],
            row["max"],
            row["out_of_range"],
            row["bound"],
        ]
        for row in rows
    ]
    return _table(["role", "coverage %", "min", "max", "out of range", "bound"], body)


def _scoreboard_table(scoreboard: pd.DataFrame) -> str:
    body = []
    for rec in scoreboard.to_dict(orient="records"):
        body.append(
            [
                rec.get("point"),
                rec.get("role"),
                rec.get("method"),
                rec.get("anomaly_minutes"),
                rec.get("event_count"),
                rec.get("skipped_reason") if pd.notna(rec.get("skipped_reason")) else "",
            ]
        )
    return _table(
        ["point", "role", "method", "anomaly min", "events", "skipped"],
        body,
    )


def _device_typst(device: dict[str, Any]) -> str:
    parts = [
        f"== {_markup_raw(device['equipment_id'])}",
        "",
        "=== 1. Data health",
        "",
        "Role coverage and physical bounds. Out-of-range counts are a quality pre-screen, not confirmed faults.",
        "",
        _health_table(device["health"]),
        "",
        "=== 2. Sensor validation",
        "",
        "Pandas oracle SV rules when the mapped sensors exist. Skipped rows are missing roles, not passes.",
        "",
        _rule_table(device["sensor_validation"]),
        "",
        "=== 3. Anomaly screening",
        "",
        _markup_raw(device["anomaly_note"]),
        "",
    ]
    board = device.get("scoreboard_preview") or []
    if board:
        parts.extend([_scoreboard_table(pd.DataFrame(board)), ""])
    parts.extend(
        [
            "=== 4. Duct static / FC1",
            "",
            "Supply-fan duct-static fault (cookbook FC1): static below setpoint while the fan is at high speed.",
            "",
            _rule_table(device["fc1"]),
            "",
        ]
    )
    if device.get("fc1_figure"):
        parts.extend([f'#image("{device["fc1_figure"]}", width: 100%)', ""])
    parts.extend(
        [
            "=== 5. Economizer performance",
            "",
            "Mixing and economizer cookbook rules (FC2, FC3, FC10, FC11, ECON-1, ECON-2, ECON-4).",
            "",
            _rule_table(device["economizer"]),
            "",
            "=== 6. Economizer scatter",
            "",
            _markup_raw(
                "economizer_delta_scatter: x = OAT - RAT (delta_or_f), "
                "y = MAT - RAT (delta_mr_f). Reference lines y = OA fraction * x "
                "for 0/25/50/75/100% OA. Fan ON and |OAT-RAT| >= 10 F. "
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
                "Scatter unavailable: need fan-on OAT, RAT, and MAT with at least five samples where |OAT-RAT| >= 10 F.",
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
    return "\n".join(
        [
            "#set page(paper: \"us-letter\", margin: 0.7in)",
            "#set text(size: 11pt)",
            f"= AHU FDD / RCx ({summary['scope']})",
            "",
            _markup_raw(_BOUNDARY),
            "",
            skip_line.rstrip(),
            body,
        ]
    )


def _is_ahu_folder(folder: Path) -> bool:
    import json

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
    methods: list[str],
    top_n: int,
    max_days: int,
    command: str | None,
) -> dict[str, Any]:
    from open_fdd.analytics.anomaly.screen import screen_folder

    device = load_device_folder(folder)
    label = equipment_label(device.column_map, folder)
    framed = role_frame(device)
    framed.attrs["equipment_id"] = label
    slug = point_slug(label)
    anomaly_dir = out_dir / "devices" / slug / "anomaly"
    screen_folder(
        folder,
        anomaly_dir,
        top_n=top_n,
        max_days=max_days,
        methods=methods,
        command=command,
    )
    scoreboard = pd.read_csv(anomaly_dir / "scoreboard.csv")
    preview = []
    for rec in scoreboard.to_dict(orient="records"):
        preview.append({key: (None if pd.isna(val) else val) for key, val in rec.items()})
    poll = _poll_seconds(framed.index)
    figures = out_dir / "figures"
    fc1_name = f"figures/{slug}_fc1.png"
    scatter_name = f"figures/{slug}_econ_scatter.png"
    fc1_ok = write_fc1_figure(framed, out_dir / fc1_name)
    scatter_ok = write_econ_scatter(framed, out_dir / scatter_name)
    fan_frac = fan_on_fraction(framed)
    fan_bit = (
        f" Mapped fan is ON for {round(100.0 * fan_frac, 1)}% of samples."
        if fan_frac is not None
        else " No fan-status or fan-cmd column is mapped."
    )
    return {
        "equipment_id": label,
        "folder": str(folder),
        "health": data_health_rows(framed, device.points),
        "sensor_validation": rule_rows(framed, SV_RULE_IDS, poll),
        "anomaly_note": ANOMALY_NOTE + fan_bit,
        "scoreboard_preview": preview,
        "fc1": rule_rows(framed, FC1_RULE_IDS, poll),
        "economizer": rule_rows(framed, ECON_RULE_IDS, poll),
        "fc1_figure": fc1_name if fc1_ok else "",
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
    top_n: int = 5,
    max_days: int = 10,
    methods: list[str] | None = None,
    command: str | None = None,
    compile_pdf: bool = False,
) -> SingleSystemReport:
    """Write ``report.typ``, ``report_summary.json``, and figure PNGs under ``out_dir``."""
    chosen = list(methods) if methods is not None else ["zscore", "mad", "stl", "iforest"]
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    folders = device_folders(folder, scope)
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
                methods=chosen,
                top_n=top_n,
                max_days=max_days,
                command=command,
            )
        )
    if not devices:
        raise ValueError(f"no AHU device folders to report under {folder}")
    summary = {
        "scope": scope,
        "boundary": _BOUNDARY,
        "devices": devices,
        "skipped": skipped,
        "sections": [
            "data_health",
            "sensor_validation",
            "anomaly_screening",
            "fc1",
            "economizer",
            "econ_scatter_oat_mat_vs_rat_mat",
        ],
    }
    summary_path = destination / "report_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    typ_path = destination / "report.typ"
    typ_path.write_text(render_typst(summary), encoding="utf-8")
    pdf_path = compile_typst(typ_path) if compile_pdf else None
    return SingleSystemReport(
        typ_path=typ_path,
        summary_path=summary_path,
        pdf_path=pdf_path,
        devices=[item["equipment_id"] for item in devices],
        skipped=skipped,
    )
