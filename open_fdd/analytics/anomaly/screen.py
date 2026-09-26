"""Orchestrate load → detect → rank → write for one device folder."""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from open_fdd.analytics.anomaly.detectors import (
    MAD_THRESHOLD,
    ZSCORE_THRESHOLD,
    anomaly_minutes,
    dedupe_events,
    is_binary_like,
    median_sample_delta,
    rolling_mad_flags,
    rolling_zscore_flags,
    samples_per_day,
)
from open_fdd.analytics.anomaly.detectors_ml import IFOREST_CONTAMINATION, STL_THRESHOLD
from open_fdd.analytics.anomaly.io import load_device_folder

VALID_METHODS = ("zscore", "mad", "stl", "iforest")
SCOREBOARD_COLUMNS = [
    "point",
    "role",
    "method",
    "anomaly_minutes",
    "event_count",
    "skipped_reason",
]


@dataclass
class ScreenResult:
    """Artifacts written by one screening run."""

    scoreboard: pd.DataFrame
    out_dir: Path
    top_points: list[str]
    days_by_point: dict[str, list[date]] = field(default_factory=dict)
    window: int = 24
    methods: list[str] = field(default_factory=list)


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _parse_methods(methods: list[str] | tuple[str, ...] | None) -> list[str]:
    chosen = list(VALID_METHODS if methods is None else methods)
    if not chosen:
        raise ValueError("at least one method is required")
    unknown = [name for name in chosen if name not in VALID_METHODS]
    if unknown:
        raise ValueError(
            f"unknown method(s): {', '.join(unknown)}; choose from {', '.join(VALID_METHODS)}"
        )
    return chosen


def _flags_for_method(method: str, series: pd.Series, *, window: int, period: int) -> pd.Series:
    if method == "zscore":
        return rolling_zscore_flags(series, window=window, threshold=ZSCORE_THRESHOLD)
    if method == "mad":
        return rolling_mad_flags(series, window=window, threshold=MAD_THRESHOLD)
    if method == "stl":
        from open_fdd.analytics.anomaly.detectors_ml import stl_residual_flags

        return stl_residual_flags(series, period=period, threshold=STL_THRESHOLD)
    if method == "iforest":
        from open_fdd.analytics.anomaly.detectors_ml import isolation_forest_flags

        return isolation_forest_flags(series, contamination=IFOREST_CONTAMINATION, random_state=42)
    raise ValueError(f"unknown method: {method}")


def _utc_dates(index: pd.DatetimeIndex) -> pd.Series:
    if getattr(index, "tz", None) is not None:
        stamped = index.tz_convert("UTC")
    else:
        stamped = index
    return pd.Series([ts.date() for ts in stamped], index=index)


def worst_days(
    flags_by_method: dict[str, pd.Series],
    median_dt: pd.Timedelta,
    max_days: int,
) -> list[date]:
    """Calendar days (UTC) with the most anomaly minutes, union across methods."""
    if max_days <= 0 or not flags_by_method:
        return []
    union: pd.Series | None = None
    for flags in flags_by_method.values():
        bit = flags.fillna(False).astype(bool)
        union = bit if union is None else union | bit
    if union is None or not bool(union.any()):
        return []
    minutes = median_dt.total_seconds() / 60.0
    daily = union.groupby(_utc_dates(union.index)).sum() * minutes
    daily = daily[daily > 0].sort_values(ascending=False)
    picked: list[date] = []
    for day in daily.head(int(max_days)).index:
        picked.append(day if isinstance(day, date) else pd.Timestamp(day).date())
    return picked


def _rank_points(scoreboard: pd.DataFrame, top_n: int) -> list[str]:
    if top_n <= 0 or scoreboard.empty:
        return []
    active = scoreboard[scoreboard["skipped_reason"].fillna("") == ""]
    if active.empty:
        return []
    totals = active.groupby("point", as_index=False)["anomaly_minutes"].sum()
    totals = totals.sort_values(["anomaly_minutes", "point"], ascending=[False, True])
    return [str(point) for point in totals["point"].head(int(top_n)).tolist()]


def _write_readme(
    path: Path,
    *,
    command: str | None,
    methods: list[str],
    window: int,
    median_dt: pd.Timedelta,
    top_n: int,
    max_days: int,
) -> None:
    method_rows = {
        "zscore": f"| zscore | SQL-portable (pandas/numpy) | abs Z-score > {ZSCORE_THRESHOLD:g} |",
        "mad": f"| mad | SQL-portable (pandas/numpy) | abs deviation / MAD > {MAD_THRESHOLD:g} |",
        "stl": (
            f"| stl | Python-only (statsmodels) | residual MAD > {STL_THRESHOLD:g}; "
            f"period = {window} samples |"
        ),
        "iforest": (
            f"| iforest | Python-only (scikit-learn) | "
            f"contamination {IFOREST_CONTAMINATION:g}; features value, rolling mean/std, lag-1 |"
        ),
    }
    lines = [
        "# Anomaly screening",
        "",
        f"Command: `{command or 'open-fdd-anomaly screen <folder> --out <outdir>'}`",
        "",
        "Calendar days are **UTC** dates from `timestamp_utc`.",
        "This run does not convert to a building-local zone such as America/Chicago.",
        "",
        "Z-score and MAD are **SQL-portable** rolling statistics (no sklearn/statsmodels).",
        "STL and Isolation Forest are **Python-only** and require `open-fdd[anomaly]`.",
        "",
        "## Methods selected",
        "",
        "| Method | Home | Rule |",
        "| --- | --- | --- |",
    ]
    for name in methods:
        lines.append(method_rows[name])
    lines.extend(
        [
            "",
            f"Trailing window: **{window}** samples (about one day at the median spacing).",
            f"Median sample interval: **{median_dt}**.",
            f"Day zooms: top **{top_n}** points, up to **{max_days}** UTC days each.",
            "Support plots (line, histogram, box) cover every screened point that was not skipped.",
            "",
            "## Versions",
            "",
            f"- pandas {_package_version('pandas')}",
            f"- numpy {_package_version('numpy')}",
            f"- matplotlib {_package_version('matplotlib')}",
            f"- statsmodels {_package_version('statsmodels')}",
            f"- scikit-learn {_package_version('scikit-learn')}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def screen_folder(
    folder: Path | str,
    out_dir: Path | str,
    *,
    top_n: int = 5,
    max_days: int = 10,
    methods: list[str] | tuple[str, ...] | None = None,
    command: str | None = None,
) -> ScreenResult:
    """Screen AHU IO points and write ``scoreboard.csv`` plus a run README.

    Plot files are added by the plotting step when it is wired in.
    """
    chosen = _parse_methods(methods)
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)

    device = load_device_folder(folder)
    window = samples_per_day(device.frame.index)
    period = max(window, 2)
    median_dt = median_sample_delta(device.frame.index)

    rows: list[dict[str, object]] = []
    flags_by_point: dict[str, dict[str, pd.Series]] = {}
    for role, column in device.points:
        series = pd.to_numeric(device.frame[column], errors="coerce")
        series.index = device.frame.index
        if series.dropna().empty:
            rows.append(
                {
                    "point": column,
                    "role": role,
                    "method": "",
                    "anomaly_minutes": 0.0,
                    "event_count": 0,
                    "skipped_reason": "non_numeric",
                }
            )
            continue
        if is_binary_like(series):
            rows.append(
                {
                    "point": column,
                    "role": role,
                    "method": "",
                    "anomaly_minutes": 0.0,
                    "event_count": 0,
                    "skipped_reason": "binary_like",
                }
            )
            continue
        point_flags: dict[str, pd.Series] = {}
        for method in chosen:
            flags = _flags_for_method(method, series, window=window, period=period)
            point_flags[method] = flags
            rows.append(
                {
                    "point": column,
                    "role": role,
                    "method": method,
                    "anomaly_minutes": anomaly_minutes(flags, median_dt),
                    "event_count": int(dedupe_events(flags).sum()),
                    "skipped_reason": "",
                }
            )
        flags_by_point[column] = point_flags

    scoreboard = pd.DataFrame(rows, columns=SCOREBOARD_COLUMNS)
    scoreboard_path = destination / "scoreboard.csv"
    scoreboard.to_csv(scoreboard_path, index=False)
    _write_readme(
        destination / "README.md",
        command=command,
        methods=chosen,
        window=window,
        median_dt=median_dt,
        top_n=int(top_n),
        max_days=int(max_days),
    )

    top_points = _rank_points(scoreboard, int(top_n))
    days_by_point = {
        point: worst_days(flags_by_point.get(point, {}), median_dt, int(max_days))
        for point in top_points
    }
    return ScreenResult(
        scoreboard=scoreboard,
        out_dir=destination,
        top_points=top_points,
        days_by_point=days_by_point,
        window=window,
        methods=chosen,
    )
