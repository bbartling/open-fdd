"""Scoreboard bar, support plots, and day-zoom PNGs (matplotlib Agg).

Day zooms follow the same layout spirit as ``open_fdd.reporting.day_zoom``:
the measured value on top, anomaly boolean strip(s) underneath.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

METHOD_COLORS = {
    "zscore": "#2563eb",
    "mad": "#16a34a",
    "stl": "#ea580c",
    "iforest": "#7c3aed",
}
_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


def point_slug(point: str) -> str:
    """Filesystem-safe point name used in plot paths."""
    cleaned = _SLUG.sub("_", str(point)).strip("._")
    return cleaned or "point"


def _pyplot():
    try:
        import matplotlib

        if "agg" not in matplotlib.get_backend().lower():
            matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError(
            "Anomaly plots require optional extra: pip install 'open-fdd[anomaly]'"
        ) from exc
    return plt


def _plot_x(index: pd.Index) -> pd.Index:
    if isinstance(index, pd.DatetimeIndex) and index.tz is not None:
        return index.tz_convert("UTC").tz_localize(None)
    return index


def _union_flags(flags_by_method: dict[str, pd.Series], index: pd.Index) -> pd.Series:
    union = pd.Series(False, index=index)
    for flags in flags_by_method.values():
        aligned = flags.reindex(index).fillna(False).astype(bool)
        union = union | aligned
    return union


def _day_slice(series: pd.Series, day: date) -> pd.Series:
    start = pd.Timestamp(datetime(day.year, day.month, day.day))
    end = start + pd.Timedelta(days=1)
    index = series.index
    if isinstance(index, pd.DatetimeIndex) and index.tz is not None:
        start = start.tz_localize("UTC").tz_convert(index.tz)
        end = end.tz_localize("UTC").tz_convert(index.tz)
    return series[(series.index >= start) & (series.index < end)]


def _draw_boxplot(ax, groups: list[np.ndarray], labels: list[str]) -> None:
    """Box plot that accepts matplotlib 3.9 ``tick_labels`` and 3.8 ``labels``."""
    try:
        ax.boxplot(groups, tick_labels=labels, showfliers=True)
    except TypeError:
        ax.boxplot(groups, labels=labels, showfliers=True)


def write_scoreboard_bar(scoreboard_df: pd.DataFrame, path: Path | str) -> Path:
    """Stacked bar of anomaly minutes per point × method."""
    plt = _pyplot()
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8.0, 4.5))
    active = scoreboard_df.copy()
    if "skipped_reason" in active.columns:
        active = active[active["skipped_reason"].fillna("").eq("")]
    active = active[active["method"].fillna("").astype(str).str.len() > 0] if "method" in active.columns else active
    if active.empty or "anomaly_minutes" not in active.columns:
        ax.set_title("No anomaly minutes")
        ax.set_axis_off()
    else:
        pivot = (
            active.pivot_table(
                index="point",
                columns="method",
                values="anomaly_minutes",
                aggfunc="sum",
            )
            .fillna(0.0)
        )
        preferred = [name for name in ("zscore", "mad", "stl", "iforest") if name in pivot.columns]
        rest = [name for name in pivot.columns if name not in preferred]
        pivot = pivot[preferred + rest]
        colors = [METHOD_COLORS.get(str(name), "#718096") for name in pivot.columns]
        pivot.plot(kind="bar", stacked=True, ax=ax, color=colors, width=0.8)
        ax.set_ylabel("Anomaly minutes")
        ax.set_xlabel("Point")
        ax.set_title("Accumulated anomaly minutes")
        ax.legend(title="method", frameon=False)
        ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def write_support_plots(
    point: str,
    series: pd.Series,
    flags_by_method: dict[str, pd.Series],
    out_dir: Path | str,
) -> None:
    """Write overview line, histogram, and box plots for one screened point."""
    plt = _pyplot()
    root = Path(out_dir)
    slug = point_slug(point)
    values = pd.to_numeric(series, errors="coerce")
    union = _union_flags(flags_by_method, values.index)
    flagged_mask = union.fillna(False).astype(bool)
    normal = values[~flagged_mask].dropna()
    flagged = values[flagged_mask].dropna()

    overview = root / "overview"
    dist = root / "dist"
    overview.mkdir(parents=True, exist_ok=True)
    dist.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(9.0, 3.6))
    x = _plot_x(values.index)
    ax.plot(x, values.to_numpy(), color="#2563eb", lw=1.1, label=point)
    if isinstance(x, pd.DatetimeIndex) or len(x) == len(flagged_mask):
        ax.fill_between(
            x,
            0,
            1,
            where=flagged_mask.to_numpy(),
            transform=ax.get_xaxis_transform(),
            color="#c53030",
            alpha=0.18,
            step="mid",
        )
    if not flagged.empty:
        ax.scatter(
            _plot_x(flagged.index),
            flagged.to_numpy(),
            s=16,
            color="#c53030",
            zorder=3,
            label="flagged",
        )
    ax.set_title(f"{point} — full span")
    ax.set_ylabel("Value")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(overview / f"{slug}_line.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    if not normal.empty:
        ax.hist(normal.to_numpy(), bins=20, color="#2563eb", alpha=0.75, label="normal")
    if not flagged.empty:
        ax.hist(flagged.to_numpy(), bins=20, color="#c53030", alpha=0.7, label="flagged")
    if normal.empty and flagged.empty:
        ax.set_axis_off()
    ax.set_title(f"{point} — distribution")
    ax.set_xlabel("Value")
    ax.set_ylabel("Samples")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(dist / f"{slug}_hist.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    groups: list[np.ndarray] = []
    labels: list[str] = []
    if not normal.empty:
        groups.append(normal.to_numpy(dtype=float))
        labels.append("normal")
    if not flagged.empty:
        groups.append(flagged.to_numpy(dtype=float))
        labels.append("flagged")
    if not groups:
        groups = [np.array([0.0])]
        labels = ["empty"]
    _draw_boxplot(ax, groups, labels)
    ax.set_title(f"{point} — box")
    ax.set_ylabel("Value")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(dist / f"{slug}_box.png", dpi=120)
    plt.close(fig)


def write_day_zoom(
    point: str,
    series: pd.Series,
    flags: pd.Series | dict[str, pd.Series],
    day: date,
    path: Path | str,
) -> Path:
    """One UTC day: value on top, one boolean strip per method underneath."""
    plt = _pyplot()
    import matplotlib.dates as mdates

    if isinstance(flags, pd.Series):
        flags_by_method: dict[str, pd.Series] = {"anomaly": flags}
    else:
        flags_by_method = dict(flags)
    if not flags_by_method:
        flags_by_method = {"anomaly": pd.Series(False, index=series.index)}

    value_day = _day_slice(pd.to_numeric(series, errors="coerce"), day)
    strips: list[tuple[str, pd.Series]] = []
    for name, mask in flags_by_method.items():
        strips.append((str(name), _day_slice(mask.astype(bool), day)))

    n_strips = len(strips)
    fig, axes = plt.subplots(
        1 + n_strips,
        1,
        sharex=True,
        figsize=(9.0, 3.2 + 0.7 * n_strips),
        gridspec_kw={"height_ratios": [3.2] + [0.8] * n_strips, "hspace": 0.08},
    )
    ax = axes[0]
    if not value_day.empty:
        ax.plot(_plot_x(value_day.index), value_day.to_numpy(), color="#2563eb", lw=1.4)
    ax.set_ylabel("Value")
    ax.grid(axis="y", alpha=0.3)
    ax.set_title(f"{point} — {day.isoformat()}", fontsize=11)

    for axis, (name, mask) in zip(axes[1:], strips, strict=True):
        axis.set_ylim(-0.1, 1.1)
        axis.set_yticks([0, 1])
        axis.set_yticklabels(["ok", "flag"])
        axis.set_ylabel(name, fontsize=8)
        if mask.empty:
            continue
        numeric = mask.fillna(False).astype(float).clip(0, 1)
        x = _plot_x(numeric.index)
        color = METHOD_COLORS.get(name, "#c53030")
        axis.fill_between(x, 0, numeric.to_numpy(), step="mid", color=color, alpha=0.55)
        ax.fill_between(
            x,
            0,
            1,
            where=numeric.to_numpy() > 0.5,
            transform=ax.get_xaxis_transform(),
            color=color,
            alpha=0.08,
            step="mid",
        )

    locator = mdates.AutoDateLocator(minticks=4, maxticks=10)
    formatter = mdates.DateFormatter("%H:%M")
    bottom = axes[-1]
    for axis in axes:
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(formatter)
    bottom.set_xlabel("Time of day (UTC)")
    for label in bottom.get_xticklabels():
        label.set_rotation(45)
        label.set_ha("right")
        label.set_fontsize(8)
    fig.subplots_adjust(hspace=0.12, bottom=0.18)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out
