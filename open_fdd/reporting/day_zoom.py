"""Per-finding worst-fault-day zoom plots (matplotlib → PNG)."""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from open_fdd.reporting.models import EngineeringFinding
from open_fdd.rules.base import RuleResult


def index_rule_results(rule_results: list[RuleResult] | None) -> dict[str, RuleResult]:
    """Map ``equipment_id|rule_id`` → RuleResult (last write wins)."""
    out: dict[str, RuleResult] = {}
    for r in rule_results or []:
        eid = getattr(r, "equipment_id", None) or ""
        rid = getattr(r, "rule_id", None) or ""
        if eid and rid:
            out[f"{eid}|{rid}"] = r
    return out


def resolve_result_for_finding(
    finding: EngineeringFinding, by_key: dict[str, RuleResult]
) -> RuleResult | None:
    """Prefer first candidate_key, else first equipment×rule combo."""
    for key in finding.candidate_keys or []:
        if key in by_key:
            return by_key[key]
    for eid in finding.equipment_ids or []:
        for rid in finding.rule_ids or []:
            hit = by_key.get(f"{eid}|{rid}")
            if hit is not None:
                return hit
    return None


def _day_bounds(day: date, index: pd.DatetimeIndex) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Inclusive start / exclusive end for ``day``, timezone-aligned to ``index``."""
    start = pd.Timestamp(day)
    end = start + pd.Timedelta(days=1)
    tz = getattr(index, "tz", None)
    if tz is not None:
        if start.tzinfo is None:
            start = start.tz_localize(tz)
            end = end.tz_localize(tz)
        else:
            start = start.tz_convert(tz)
            end = end.tz_convert(tz)
    elif start.tzinfo is not None:
        start = start.tz_convert("UTC").tz_localize(None)
        end = end.tz_convert("UTC").tz_localize(None)
    return start, end


def worst_fault_day(fault: pd.Series | None) -> date | None:
    """Calendar day with the most fault samples (True / 1)."""
    if fault is None or len(fault) == 0:
        return None
    s = fault.dropna()
    if s.empty:
        return None
    # Coerce to 0/1
    try:
        numeric = s.astype(float)
    except (TypeError, ValueError):
        numeric = s.map(lambda v: 1.0 if bool(v) else 0.0)
    if not isinstance(s.index, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(s.index)
            numeric.index = idx
        except Exception:
            return None
    else:
        numeric.index = s.index
    daily = numeric.groupby(numeric.index.normalize()).sum()
    if daily.empty or float(daily.max()) <= 0:
        return None
    day_ts = daily.idxmax()
    if isinstance(day_ts, datetime):
        return day_ts.date()
    if isinstance(day_ts, pd.Timestamp):
        return day_ts.date()
    if isinstance(day_ts, date):
        return day_ts
    try:
        return pd.Timestamp(day_ts).date()
    except Exception:
        return None


def render_day_zoom_png(
    result: RuleResult,
    day: date,
    out_path: Path,
    *,
    max_series: int = 4,
) -> tuple[Path, float] | None:
    """Matplotlib day zoom: plot_series + fault lane for ``day``.

    Returns ``(path, fault_hours_that_day)`` or None.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    fault = getattr(result, "confirmed_fault", None)
    if fault is None or (hasattr(fault, "empty") and fault.empty):
        fault = getattr(result, "raw_fault", None)
    plot_series = getattr(result, "plot_series", None) or {}

    def _slice(ser: pd.Series | None) -> pd.Series | None:
        if ser is None or len(ser) == 0:
            return None
        s = ser.copy()
        if not isinstance(s.index, pd.DatetimeIndex):
            try:
                s.index = pd.to_datetime(s.index)
            except Exception:
                return None
        day_start, day_end = _day_bounds(day, s.index)
        return s[(s.index >= day_start) & (s.index < day_end)]

    fault_day = _slice(fault)
    series_day: list[tuple[str, pd.Series]] = []
    for name, ser in list(plot_series.items())[:max_series]:
        sl = _slice(ser if isinstance(ser, pd.Series) else None)
        if sl is not None and not sl.empty:
            series_day.append((str(name), sl))

    if (fault_day is None or fault_day.empty) and not series_day:
        return None

    fig, (ax, ax_f) = plt.subplots(
        2,
        1,
        figsize=(9.0, 4.2),
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 0.8], "hspace": 0.08},
    )
    colors = ["#2b6cb0", "#c05621", "#2f855a", "#805ad5"]
    for i, (name, sl) in enumerate(series_day):
        try:
            y = pd.to_numeric(sl, errors="coerce")
        except Exception:
            y = sl
        ax.plot(y.index, y.values, label=name, color=colors[i % len(colors)], lw=1.4)
    if series_day:
        ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.set_ylabel("Value")
    ax.grid(axis="y", alpha=0.3)
    ax.set_title(
        f"{getattr(result, 'equipment_id', '')} · {getattr(result, 'rule_id', '')} — {day.isoformat()}",
        fontsize=11,
    )

    # Fault lane
    ax_f.set_ylim(-0.1, 1.1)
    ax_f.set_yticks([0, 1])
    ax_f.set_yticklabels(["ok", "fault"])
    ax_f.set_xlabel("Time of day")
    if fault_day is not None and not fault_day.empty:
        try:
            fnum = fault_day.astype(float).clip(0, 1)
        except Exception:
            fnum = fault_day.map(lambda v: 1.0 if bool(v) else 0.0)
        ax_f.fill_between(
            fnum.index,
            0,
            fnum.values,
            step="mid",
            color="#c53030",
            alpha=0.55,
            label="fault",
        )
        ax.fill_between(
            fnum.index,
            0,
            1,
            where=fnum.values > 0.5,
            transform=ax.get_xaxis_transform(),
            color="#c53030",
            alpha=0.08,
            step="mid",
        )

    fault_hours = 0.0
    if fault_day is not None and not fault_day.empty:
        try:
            vals = fault_day.astype(float)
            n_true = float((vals > 0.5).sum())
            if len(vals) > 1:
                dt_h = (
                    (vals.index.max() - vals.index.min()).total_seconds() / 3600.0
                ) / max(len(vals) - 1, 1)
                fault_hours = n_true * dt_h
            else:
                fault_hours = n_true
        except Exception:
            fault_hours = float(fault_day.astype(bool).sum())

    # Title already has the calendar day — x ticks are clock time only.
    import matplotlib.dates as mdates

    locator = mdates.AutoDateLocator(minticks=4, maxticks=10)
    formatter = mdates.DateFormatter("%H:%M")
    for axis in (ax, ax_f):
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(formatter)
        for label in axis.get_xticklabels():
            label.set_rotation(45)
            label.set_ha("right")
            label.set_fontsize(8)
    ax_f.tick_params(axis="x", which="both", labelbottom=True)
    ax.tick_params(axis="x", which="both", labelbottom=False)

    fig.subplots_adjust(hspace=0.12, bottom=0.22)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    out_path.write_bytes(buf.getvalue())
    return out_path, round(fault_hours, 2)


def attach_day_zoom_to_findings(
    findings: list[EngineeringFinding],
    rule_results: list[RuleResult] | None,
    *,
    out_dir: Path,
) -> list[dict[str, Any]]:
    """Write day-zoom PNGs and set ``day_zoom_path`` / ``day_zoom_label`` on findings.

    Always records a meta per included finding. Successful zooms include ``path``;
    skips include ``skip_reason`` in ``{no_result, no_fault_day, render_failed}``
    and set ``EngineeringFinding.day_zoom_skip_reason``. Findings with
    ``include_in_report=False`` are ignored (no meta).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_key = index_rule_results(rule_results)
    metas: list[dict[str, Any]] = []

    def _skip(f: EngineeringFinding, reason: str) -> None:
        f.day_zoom_path = None
        f.day_zoom_skip_reason = reason
        f.day_zoom_label = f"Day-zoom unavailable: {reason}"
        metas.append(
            {
                "name": f"day_zoom_{f.finding_id}",
                "finding_id": f.finding_id,
                "skip_reason": reason,
            }
        )

    for f in findings:
        if not f.include_in_report:
            continue
        result = resolve_result_for_finding(f, by_key)
        if result is None:
            _skip(f, "no_result")
            continue
        fault = getattr(result, "confirmed_fault", None)
        if fault is None or (hasattr(fault, "empty") and fault.empty):
            fault = getattr(result, "raw_fault", None)
        day = worst_fault_day(fault if isinstance(fault, pd.Series) else None)
        if day is None:
            _skip(f, "no_fault_day")
            continue
        png = out_dir / f"day_zoom_{f.finding_id}.png"
        try:
            rendered = render_day_zoom_png(result, day, png)
        except Exception:
            _skip(f, "render_failed")
            continue
        if rendered is None:
            _skip(f, "render_failed")
            continue
        path, hours = rendered
        if not path.is_file():
            _skip(f, "render_failed")
            continue
        label = f"{day.isoformat()} · ~{hours:g} fault-h that day"
        f.day_zoom_path = str(path)
        f.day_zoom_label = label
        f.day_zoom_skip_reason = None
        metas.append(
            {
                "name": f"day_zoom_{f.finding_id}",
                "path": str(path),
                "finding_id": f.finding_id,
                "title": label,
            }
        )
    return metas
