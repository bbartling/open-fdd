"""Orchestrate load → detect → rank → write for one device folder."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from open_fdd.analytics.anomaly.activity import (
    ACTIVITY_POLICIES,
    DEFAULT_POLICY,
    SKIP_NO_ACTIVE,
    SKIP_NO_KNOWN_PROOF,
    SKIP_NO_PROOF,
    activity,
    is_site_role,
)
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
#: Run when ``methods`` is not given, each only if its optional dependency imports (#1654). Isolation Forest is
#: opt-in: it marks a fixed fraction of every point by construction (#1658).
DEFAULT_METHODS = ("zscore", "mad", "stl")
#: ``method: (import name, pip extra)`` for the Python-only methods.
METHOD_EXTRAS: dict[str, tuple[str, str]] = {
    "stl": ("statsmodels", "open-fdd[anomaly]"),
    "iforest": ("sklearn", "open-fdd[anomaly]"),
}


def method_available(method: str) -> bool:
    """True when the method's optional dependency imports (z-score and MAD need only pandas)."""
    need = METHOD_EXTRAS.get(method)
    return need is None or importlib.util.find_spec(need[0]) is not None


def default_methods() -> tuple[list[str], dict[str, str]]:
    """``(runnable default methods, {skipped method: why})`` for this install."""
    run, skipped = [], {}
    for name in DEFAULT_METHODS:
        if method_available(name):
            run.append(name)
        else:
            module, extra = METHOD_EXTRAS[name]
            skipped[name] = f"{module} is not installed: pip install \"{extra}\""
    return run, skipped
#: ``pandas`` (default) or ``sql``: where the z-score runs. ``sql`` runs ``sql/analytics/anomaly_zscore.sql`` on an
#: in-process SQLite core (``open_fdd.analytics.sql_anomaly``); the other methods always run in Python.
VALID_ENGINES = ("pandas", "sql")
SCOREBOARD_COLUMNS = [
    "point",
    "role",
    "method",
    "anomaly_minutes",
    "event_count",
    "skipped_reason",
    "gate",
    "assessed_rows",
    "method_note",
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
    activity: dict[str, object] = field(default_factory=dict)
    methods_skipped: dict[str, str] = field(default_factory=dict)


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _parse_methods(methods: list[str] | tuple[str, ...] | None) -> list[str]:
    chosen = list(default_methods()[0] if methods is None else methods)
    if not chosen:
        raise ValueError("at least one method is required")
    unknown = [name for name in chosen if name not in VALID_METHODS]
    if unknown:
        raise ValueError(
            f"unknown method(s): {', '.join(unknown)}; choose from {', '.join(VALID_METHODS)}"
        )
    return chosen


def _flags_for_method(
    method: str,
    series: pd.Series,
    *,
    window: int,
    period: int,
    contamination: float = IFOREST_CONTAMINATION,
) -> pd.Series:
    if method == "zscore":
        return rolling_zscore_flags(series, window=window, threshold=ZSCORE_THRESHOLD)
    if method == "mad":
        return rolling_mad_flags(series, window=window, threshold=MAD_THRESHOLD)
    if method == "stl":
        from open_fdd.analytics.anomaly.detectors_ml import stl_residual_flags

        return stl_residual_flags(series, period=period, threshold=STL_THRESHOLD)
    if method == "iforest":
        from open_fdd.analytics.anomaly.detectors_ml import isolation_forest_flags

        return isolation_forest_flags(series, contamination=contamination, random_state=42)
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
    engine: str = "pandas",
    activity_receipt: dict[str, object] | None = None,
    methods_skipped: dict[str, str] | None = None,
    contamination: float = IFOREST_CONTAMINATION,
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
            f"contamination {contamination:g}: flags about {contamination:.1%} of every point's samples by "
            f"construction, whether or not anything happened (opt-in); features value, rolling mean/std, lag-1 |"
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
        f"Z-score engine: **{engine}**"
        + (" (`sql/analytics/anomaly_zscore.sql` on in-process SQLite, each point's non-missing samples)."
           if engine == "sql" else " (pandas)."),
        "",
        "## Methods selected",
        "",
        "| Method | Home | Rule |",
        "| --- | --- | --- |",
    ]
    for name in methods:
        lines.append(method_rows[name])
    for name, why in (methods_skipped or {}).items():
        lines.append(f"| {name} | skipped | {why} |")
    if activity_receipt:
        a = activity_receipt
        policy = a.get("policy")
        lines.extend(
            [
                "",
                "## Activity",
                "",
                f"Policy: **{policy}**"
                + (
                    " (every row screened on purpose; proof counts below are for disclosure)."
                    if policy == "ungated"
                    else " (equipment points are screened only on rows with operating proof `on`;"
                    " site and weather points are always screened)."
                ),
                f"Proof source: **{a.get('proof_source')}** ({a.get('proof_kind')}"
                + (f", > {a.get('threshold')}" if a.get("threshold") is not None else "")
                + f"); occupancy source: **{a.get('occupancy_source')}**.",
                f"Rows: {a.get('rows')} total; on {a.get('on_rows')}, off {a.get('off_rows')}, "
                f"unoccupied {a.get('unoccupied_rows')}, unknown {a.get('unknown_rows')}.",
                f"Assessed equipment rows: **{a.get('assessed_rows')}** ({float(a.get('assessed_fraction') or 0):.1%}).",
                "Equipment points with no assessable rows are listed with `skipped_reason` "
                f"`{SKIP_NO_PROOF}` (no proof role), `{SKIP_NO_KNOWN_PROOF}` (a proof role with no known value on any row) "
                f"or `{SKIP_NO_ACTIVE}` (proof never on); they were not assessed.",
                "The scoreboard's `gate` column says how each point was gated and `assessed_rows` how many rows it had.",
            ]
        )
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


def _write_plots(
    destination: Path,
    *,
    scoreboard: pd.DataFrame,
    screened: dict[str, pd.Series],
    flags_by_point: dict[str, dict[str, pd.Series]],
    top_points: list[str],
    days_by_point: dict[str, list[date]],
) -> None:
    from open_fdd.analytics.anomaly.plots import (
        point_slug,
        write_day_zoom,
        write_scoreboard_bar,
        write_support_plots,
    )

    write_scoreboard_bar(scoreboard, destination / "scoreboard_bar.png")
    for point, series in screened.items():
        write_support_plots(point, series, flags_by_point.get(point, {}), destination)
    for point in top_points:
        series = screened.get(point)
        if series is None:
            continue
        flags = flags_by_point.get(point, {})
        slug = point_slug(point)
        for day in days_by_point.get(point, []):
            write_day_zoom(
                point,
                series,
                flags,
                day,
                destination / "days" / slug / f"{day.isoformat()}.png",
            )


def screen_folder(
    folder: Path | str,
    out_dir: Path | str,
    *,
    top_n: int = 5,
    max_days: int = 10,
    methods: list[str] | tuple[str, ...] | None = None,
    command: str | None = None,
    engine: str = "pandas",
    activity_policy: str = DEFAULT_POLICY,
    iforest_contamination: float = IFOREST_CONTAMINATION,
) -> ScreenResult:
    """Screen AHU IO points and write the scoreboard, README, and plots.

    Support plots cover every non-skipped point. Day zooms cover the top
    ``top_n`` points and at most ``max_days`` UTC days each. ``engine="sql"``
    computes the z-score with the portable SQL query instead of pandas.

    ``activity_policy="proof"`` (default) screens equipment points only on rows the shared activity
    policy (:mod:`open_fdd.analytics.anomaly.activity`, also used by ``open-fdd-ml detect``) marks ``on``;
    the detectors then run over those rows in order. Site and weather points are always screened.
    ``"ungated"`` screens every row on purpose. The policy, proof source and on/off/unknown counts are
    written to ``activity.json`` and the README.
    """
    chosen = _parse_methods(methods)
    skipped_methods = default_methods()[1] if methods is None else {}
    rate = float(iforest_contamination)
    if not 0.0 < rate <= 0.5:
        raise ValueError("iforest contamination must be in (0, 0.5]")
    if engine not in VALID_ENGINES:
        raise ValueError(f"unknown engine {engine!r}; choose from {', '.join(VALID_ENGINES)}")
    if activity_policy not in ACTIVITY_POLICIES:
        raise ValueError(
            f"unknown activity policy {activity_policy!r}; choose from {', '.join(ACTIVITY_POLICIES)}"
        )
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)

    device = load_device_folder(folder)
    window = samples_per_day(device.frame.index)
    period = max(window, 2)
    median_dt = median_sample_delta(device.frame.index)

    # Proof roles may sit outside the AHU IO set, so read them from every mapped point.
    every = load_device_folder(folder, ahu_only=False)
    role_frame = pd.DataFrame(
        {role: every.frame[column] for role, column in reversed(every.points)},
        index=every.frame.index,
    )
    act = activity(role_frame, policy=activity_policy)
    on_rows = act.state.eq("on")
    if on_rows.index.equals(device.frame.index):
        running = pd.Series(on_rows.to_numpy(dtype=bool), index=device.frame.index)
    else:
        running = on_rows[~on_rows.index.duplicated()].reindex(device.frame.index).fillna(False).astype(bool)

    def _gate(role: str) -> tuple[str, pd.Series]:
        if activity_policy == "ungated":
            return "ungated", pd.Series(True, index=device.frame.index)
        if is_site_role(role):
            return "site", pd.Series(True, index=device.frame.index)
        return "proof", running

    sql_zscore: pd.DataFrame | None = None
    if engine == "sql" and "zscore" in chosen:
        from open_fdd.analytics.sql_anomaly import zscore_flags_sql

        columns = list(dict.fromkeys(column for _role, column in device.points))
        numeric = device.frame[columns].apply(pd.to_numeric, errors="coerce")
        for role, column in device.points:
            numeric[column] = numeric[column].where(_gate(role)[1].to_numpy())
        sql_zscore = zscore_flags_sql(numeric, window=window, threshold=ZSCORE_THRESHOLD, engine="sqlite")

    rows: list[dict[str, object]] = []
    flags_by_point: dict[str, dict[str, pd.Series]] = {}
    screened: dict[str, pd.Series] = {}
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
                    "gate": _gate(role)[0],
                    "assessed_rows": 0,
                    "method_note": "",
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
                    "gate": _gate(role)[0],
                    "assessed_rows": 0,
                    "method_note": "",
                }
            )
            continue
        gate, assessed = _gate(role)
        assessed_rows = int((assessed & series.notna()).sum())
        if not bool(assessed.any()):
            rows.append(
                {
                    "point": column,
                    "role": role,
                    "method": "",
                    "anomaly_minutes": 0.0,
                    "event_count": 0,
                    "skipped_reason": act.skip_reason(),
                    "gate": gate,
                    "assessed_rows": 0,
                    "method_note": "",
                }
            )
            continue
        gated = series if bool(assessed.all()) else series[assessed.to_numpy()]
        point_flags: dict[str, pd.Series] = {}
        for method in chosen:
            if method == "zscore" and sql_zscore is not None:
                flags = sql_zscore[column].astype(bool)
            else:
                flags = _flags_for_method(method, gated, window=window, period=period, contamination=rate)
                if gated is not series:
                    # positional: a device folder may carry duplicate timestamps, which reindex cannot align
                    full = np.zeros(len(series), dtype=bool)
                    full[np.flatnonzero(assessed.to_numpy())] = flags.to_numpy(dtype=bool)
                    flags = pd.Series(full, index=series.index)
            flags = (flags.astype(bool) & assessed.to_numpy()).astype(bool)
            point_flags[method] = flags
            rows.append(
                {
                    "point": column,
                    "role": role,
                    "method": method,
                    "anomaly_minutes": anomaly_minutes(flags, median_dt),
                    "event_count": int(dedupe_events(flags).sum()),
                    "skipped_reason": "",
                    "gate": gate,
                    "assessed_rows": assessed_rows,
                    "method_note": f"fixed_fraction_{rate:g}" if method == "iforest" else "",
                }
            )
        flags_by_point[column] = point_flags
        screened[column] = series

    scoreboard = pd.DataFrame(rows, columns=SCOREBOARD_COLUMNS)
    scoreboard_path = destination / "scoreboard.csv"
    scoreboard.to_csv(scoreboard_path, index=False)
    receipt = act.receipt()
    (destination / "activity.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    _write_readme(
        destination / "README.md",
        command=command,
        methods=chosen,
        window=window,
        median_dt=median_dt,
        top_n=int(top_n),
        max_days=int(max_days),
        engine=engine,
        activity_receipt=receipt,
        methods_skipped=skipped_methods,
        contamination=rate,
    )

    top_points = _rank_points(scoreboard, int(top_n))
    days_by_point = {
        point: worst_days(flags_by_point.get(point, {}), median_dt, int(max_days))
        for point in top_points
    }
    _write_plots(
        destination,
        scoreboard=scoreboard,
        screened=screened,
        flags_by_point=flags_by_point,
        top_points=top_points,
        days_by_point=days_by_point,
    )
    return ScreenResult(
        scoreboard=scoreboard,
        out_dir=destination,
        top_points=top_points,
        days_by_point=days_by_point,
        window=window,
        methods=chosen,
        activity=receipt,
        methods_skipped=skipped_methods,
    )
