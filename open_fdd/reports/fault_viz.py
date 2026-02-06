"""
Fault visualization for config-driven FDD.

Provides zoom-on-event plots, fault analytics charts, and helpers to keep
notebooks beginner-friendly by hiding implementation details.
"""

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Optional seaborn for nicer default styling
try:
    import seaborn as sns

    sns.set_theme(style="whitegrid", palette="muted")
except ImportError:
    pass


# Default signal columns when rule has none (common AHU sensors)
DEFAULT_SIGNAL_COLS = [
    "SAT (°F)",
    "MAT (°F)",
    "OAT (°F)",
    "RAT (°F)",
    "SA Static Press (inH₂O)",
    "SF Spd Cmd (%)",
    "OA Damper Cmd (%)",
    "Clg Vlv Cmd (%)",
    "Prht Vlv Cmd (%)",
]


def get_fault_events(df: pd.DataFrame, flag_col: str) -> List[Tuple[int, int, str]]:
    """
    Return list of (start_iloc, end_iloc, flag_name) for contiguous fault regions.
    """
    s = df[flag_col].astype(bool)
    if not s.any():
        return []
    groups = (~s).cumsum()
    fault_groups = groups[s]
    events = []
    for g in fault_groups.unique():
        idx = fault_groups[fault_groups == g].index
        pos = df.index.get_indexer(idx)
        events.append((int(pos.min()), int(pos.max()), flag_col))
    return events


def all_fault_events(
    df: pd.DataFrame, flag_cols: List[str]
) -> List[Tuple[int, int, str]]:
    """Collect events from all flag columns, sorted by start time."""
    events = []
    for col in flag_cols:
        events.extend(get_fault_events(df, col))
    return sorted(events, key=lambda e: e[0])


def build_rule_sensor_mapping(
    rules: List[Dict],
    result: pd.DataFrame,
    column_map: Dict[str, str],
) -> Tuple[Dict[str, List[str]], Dict[str, Dict]]:
    """
    Build fault-specific sensor mapping from rules.

    Returns:
        (rule_to_sensors, rule_by_flag)
        - rule_to_sensors: {flag: [csv_col, ...]}
        - rule_by_flag: {flag: rule_dict}
    """
    rule_to_sensors = {}
    rule_by_flag = {}
    for r in rules:
        flag = r.get("flag")
        if not flag:
            continue
        rule_by_flag[flag] = r
        cols = []
        for key, val in r.get("inputs", {}).items():
            c = _resolve_input_to_col(
                val if isinstance(val, dict) else {"column": val}, column_map
            )
            if c and c in result.columns and c not in cols:
                cols.append(c)
        rule_to_sensors[flag] = cols
    return rule_to_sensors, rule_by_flag


def build_sensor_map_for_summarize(
    rules: List[Dict],
    result: pd.DataFrame,
    column_map: Dict[str, str],
) -> Dict[str, Dict[str, str]]:
    """
    Build {flag: {label: column}} for summarize_fault sensor_cols.
    """
    sensor_map = {}
    for r in rules:
        flag = r.get("flag")
        if not flag:
            continue
        sensor_map[flag] = {}
        for key, val in r.get("inputs", {}).items():
            col = _resolve_input_to_col(
                val if isinstance(val, dict) else {"column": val}, column_map
            )
            if col and col in result.columns:
                label = key.replace("_", " ")
                sensor_map[flag][label] = col
    return sensor_map


def _resolve_input_to_col(inp: Any, column_map: Dict[str, str]) -> Optional[str]:
    """Resolve rule input to CSV column name."""
    if isinstance(inp, str):
        return column_map.get(inp, inp)
    brick = inp.get("brick")
    col = inp.get("column", "")
    return (
        column_map.get(brick)
        or column_map.get(f"{brick}|{col}")
        or column_map.get(col)
        or col
    )


def zoom_on_event(
    df: pd.DataFrame,
    event: Tuple[int, int, str],
    pad: int = 24,
    signal_cols: Optional[List[str]] = None,
    rule_to_sensors: Optional[Dict[str, List[str]]] = None,
    rule_by_flag: Optional[Dict[str, Dict]] = None,
    column_map: Optional[Dict[str, str]] = None,
    fallback_cols: Optional[List[str]] = None,
):
    """
    Plot fault-specific signals around an event. pad = samples before/after.

    Uses ffill/bfill so lines are continuous (no gaps from NaNs).
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    from open_fdd.engine.checks import check_bounds, check_flatline

    start_iloc, end_iloc, flag_name = event
    center = (start_iloc + end_iloc) // 2
    lo = max(0, center - pad)
    hi = min(len(df) - 1, center + pad)
    window = df.iloc[lo : hi + 1]

    if signal_cols is None and rule_to_sensors and rule_by_flag and column_map:
        signal_cols = _get_sensors_for_event(
            window, flag_name, rule_to_sensors, rule_by_flag, df, column_map
        )
    if not signal_cols:
        if fallback_cols is None:
            fallback_cols = [c for c in DEFAULT_SIGNAL_COLS if c in df.columns]
        signal_cols = fallback_cols
    signal_cols = [c for c in signal_cols if c in window.columns]

    n_axes = len(signal_cols) + 1
    fig, axes = plt.subplots(n_axes, 1, figsize=(12, 2 * n_axes), sharex=True)
    if n_axes == 1:
        axes = [axes]

    ts = window["timestamp"] if "timestamp" in window.columns else window.index

    for ax, col in zip(axes[:-1], signal_cols):
        if col in window.columns:
            series = window[col].ffill().bfill()
            ax.plot(ts, series, color="#2e86ab", linewidth=1.2)
        ax.set_ylabel(col, fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.yaxis.set_major_locator(plt.MaxNLocator(5))
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

    flag_vals = (
        window[flag_name]
        if flag_name in window.columns
        else pd.Series(0, index=window.index)
    )
    axes[-1].fill_between(ts, 0, flag_vals, color="#e94f37", alpha=0.6, step="post")
    axes[-1].set_ylabel(flag_name, fontsize=9)
    axes[-1].set_ylim(-0.1, 1.2)
    axes[-1].grid(True, alpha=0.3)

    fault_lo = max(0, start_iloc - lo)
    fault_hi = min(len(window) - 1, end_iloc - lo)
    if fault_lo <= fault_hi:
        for ax in axes[:-1]:
            ax.axvspan(
                ts.iloc[fault_lo], ts.iloc[fault_hi], alpha=0.15, color="#e94f37"
            )

    t0, t1 = ts.iloc[0], ts.iloc[-1]
    t0_str = t0.strftime("%Y-%m-%d %H:%M") if hasattr(t0, "strftime") else str(t0)
    t1_str = t1.strftime("%Y-%m-%d %H:%M") if hasattr(t1, "strftime") else str(t1)
    fig.suptitle(f"{flag_name}: {t0_str} to {t1_str}", fontsize=11)
    plt.tight_layout()
    return fig


def _resolve_bounds(inp: Dict, rule: Dict, units: str = "imperial") -> Optional[List]:
    raw = inp.get("bounds", rule.get("bounds"))
    if not raw:
        return None
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return list(raw)
    if isinstance(raw, dict):
        return raw.get(units) or raw.get("imperial")
    return None


def _get_sensors_for_event(
    window: pd.DataFrame,
    flag_name: str,
    rule_to_sensors: Dict[str, List[str]],
    rule_by_flag: Dict[str, Dict],
    df_full: pd.DataFrame,
    column_map: Dict[str, str],
) -> List[str]:
    """Get fault-specific sensors. For bounds/flatline: only sensors in trouble."""
    from open_fdd.engine.checks import check_bounds, check_flatline

    rule = rule_by_flag.get(flag_name)
    candidates = rule_to_sensors.get(flag_name, [])
    if not rule or rule.get("type") not in ("bounds", "flatline"):
        return [c for c in candidates if c in window.columns]
    in_trouble = []
    if rule.get("type") == "bounds":
        units = (rule.get("params") or {}).get("units", "imperial")
        for key, inp in rule.get("inputs", {}).items():
            if not isinstance(inp, dict):
                continue
            col = _resolve_input_to_col(inp, column_map)
            if col not in window.columns:
                continue
            bounds = _resolve_bounds(inp, rule, units)
            if not bounds:
                continue
            low, high = bounds
            if check_bounds(window[col], low, high).any():
                in_trouble.append(col)
    elif rule.get("type") == "flatline":
        params = rule.get("params") or {}
        tol = params.get("tolerance", 0.000001)
        win = params.get("window", 12)
        for col in candidates:
            if col not in window.columns:
                continue
            if check_flatline(window[col], tolerance=tol, window=win).any():
                in_trouble.append(col)
    return in_trouble if in_trouble else candidates


def run_fault_analytics(
    result: pd.DataFrame,
    flag_cols: List[str],
    rules: List[Dict],
    column_map: Dict[str, str],
    flatline_window: int = 12,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute summarize_fault for each flag. Returns {flag: summary_dict}.
    """
    from open_fdd.reports import flatline_period_range, summarize_fault

    sensor_map = build_sensor_map_for_summarize(rules, result, column_map)
    result_idx = (
        result.set_index("timestamp") if "timestamp" in result.columns else result
    )
    motor_col = "SF Spd Cmd (%)" if "SF Spd Cmd (%)" in result.columns else None

    summaries = {}
    for fc in flag_cols:
        sensors = sensor_map.get(fc)
        period_range = None
        if fc == "flatline_flag" and "flatline_flag" in result_idx.columns:
            period_range = flatline_period_range(
                result_idx.reset_index(),
                flag_col=fc,
                timestamp_col="timestamp",
                window=flatline_window,
            )
        summaries[fc] = summarize_fault(
            result_idx,
            fc,
            sensor_cols=sensors,
            motor_col=motor_col,
            period_range=period_range,
        )
    return summaries


def plot_fault_analytics(
    result: pd.DataFrame,
    flag_cols: List[str],
    events: List[Tuple[int, int, str]],
    summaries: Dict[str, Dict[str, Any]],
):
    """Plot fault sample counts (bar) + event duration histogram."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    counts = [int(result[c].sum()) for c in flag_cols]
    axes[0].bar(range(len(flag_cols)), counts, color="#2e86ab", alpha=0.8)
    axes[0].set_xticks(range(len(flag_cols)))
    axes[0].set_xticklabels(flag_cols, rotation=45, ha="right")
    axes[0].set_ylabel("Fault samples")
    axes[0].set_title("Fault sample counts per flag")

    durations = [e[1] - e[0] + 1 for e in events]
    axes[1].hist(
        durations,
        bins=min(50, len(set(durations))),
        color="#2e86ab",
        alpha=0.8,
        edgecolor="white",
    )
    axes[1].set_xlabel("Event duration (samples)")
    axes[1].set_ylabel("Count")
    axes[1].set_title("Fault event duration distribution")
    plt.tight_layout()
    plt.show()


def plot_flag_true_bars(
    summaries: Dict[str, Dict[str, Any]],
    flag_cols: List[str],
):
    """Plot flag_true_* (mean sensor value when fault active) as horizontal bar charts."""
    import matplotlib.pyplot as plt

    n_flags = len(flag_cols)
    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    axes = axes.flatten()
    for idx, fc in enumerate(flag_cols):
        ax = axes[idx]
        s = summaries.get(fc, {})
        labels = [
            k.replace("flag_true_", "").replace("_", " ")
            for k in s
            if k.startswith("flag_true_")
        ]
        vals = [
            s[k]
            for k in s
            if k.startswith("flag_true_") and isinstance(s[k], (int, float))
        ]
        if labels and vals:
            y_pos = range(len(labels))
            ax.barh(y_pos, vals, color="#2e86ab", alpha=0.8)
            ax.set_yticks(y_pos)
            ax.set_yticklabels(labels, fontsize=8)
            ax.set_xlabel("Mean when fault active")
            ax.set_title(fc, fontsize=10)
        else:
            ax.text(
                0.5,
                0.5,
                "No sensor stats",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_title(fc, fontsize=10)
    for j in range(idx + 1, len(axes)):
        axes[j].axis("off")
    plt.suptitle("Sensor means during fault (flag_true_*)", fontsize=12)
    plt.tight_layout()
    plt.show()
