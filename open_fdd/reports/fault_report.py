"""
Fault analytics and reporting for config-driven FDD.

Provides fault duration, motor runtime, sensor stats, and time-range helpers.
"""

from typing import Any, Dict, List, Optional

import pandas as pd


def sensor_cols_from_column_map(column_map: Dict[str, str]) -> Dict[str, str]:
    """
    Return sensor entries from column_map (excludes motor/command columns).
    Use for summarize_fault and analyze_*_episodes.
    """
    return {k: v for k, v in column_map.items() if "Sensor" in k}


def print_column_mapping(label: str, mapping: Dict[str, str]) -> None:
    """
    Print column mapping. Falls back to ASCII-safe on Windows (cp1252) if Unicode fails.
    """
    try:
        print(f"{label}: {mapping}")
    except UnicodeEncodeError:
        safe = {k: v.encode("ascii", "replace").decode() for k, v in mapping.items()}
        print(f"{label}: {safe}")


def time_range(
    df: pd.DataFrame,
    flag_col: str,
    timestamp_col: str = "timestamp",
) -> str:
    """
    Return time range string for faulted rows.

    Args:
        df: DataFrame with fault flags and timestamps.
        flag_col: Name of fault flag column (0/1).
        timestamp_col: Column with timestamps.

    Returns:
        String like "2025-01-01 03:00:00 to 2025-01-01 06:15:00" or "-" if no faults.
    """
    faulted = df[df[flag_col] == 1]
    if faulted.empty:
        return "-"
    ts = faulted[timestamp_col]
    if len(ts) == 1:
        return str(ts.iloc[0])
    return f"{ts.min()} to {ts.max()}"


def flatline_period_range(
    df: pd.DataFrame,
    flag_col: str = "flatline_flag",
    timestamp_col: str = "timestamp",
    window: int = 12,
) -> Optional[tuple]:
    """
    Return (start_ts, end_ts) for the full flatline period, or None if no faults.
    Use this to get period bounds that match the flatline_period string.
    """
    faulted = df[df[flag_col] == 1]
    if faulted.empty:
        return None
    first_idx = df[df[flag_col] == 1].index.min()
    start_idx = first_idx - (window - 1)
    if start_idx >= 0:
        start_ts = pd.Timestamp(df.loc[start_idx, timestamp_col])
        end_ts = pd.Timestamp(faulted[timestamp_col].max())
        return (start_ts, end_ts)
    return (
        pd.Timestamp(faulted[timestamp_col].min()),
        pd.Timestamp(faulted[timestamp_col].max()),
    )


def flatline_period(
    df: pd.DataFrame,
    flag_col: str = "flatline_flag",
    timestamp_col: str = "timestamp",
    window: int = 12,
) -> str:
    """
    Return full flatline period (when data was flat), not just when flag=1.

    Flatline rules need `window` identical values before flagging, so the actual
    flat period starts ~(window-1) rows before the first flagged row.

    Args:
        df: DataFrame with fault flags and timestamps.
        flag_col: Name of flatline flag column.
        timestamp_col: Column with timestamps.
        window: Rolling window from the flatline rule (e.g. 12 from sensor_flatline.yaml).

    Returns:
        String like "2025-01-01 03:00:00 to 2025-01-01 06:15:00" or "-" if no faults.
    """
    faulted = df[df[flag_col] == 1]
    if faulted.empty:
        return "-"
    start_idx = df[df[flag_col] == 1].index.min() - (window - 1)
    if start_idx >= 0:
        start_ts = df.loc[start_idx, timestamp_col]
        end_ts = faulted[timestamp_col].max()
        return f"{start_ts} to {end_ts}"
    return time_range(df, flag_col, timestamp_col)


def summarize_fault(
    df: pd.DataFrame,
    flag_col: str,
    timestamp_col: Optional[str] = None,
    sensor_cols: Optional[Dict[str, str]] = None,
    motor_col: Optional[str] = None,
    period_range: Optional[tuple] = None,
) -> Dict[str, Any]:
    """
    Compute fault analytics for a single fault flag.

    Args:
        df: DataFrame with datetime index or timestamp_col.
        flag_col: Name of fault flag column (0/1).
        timestamp_col: If df has no datetime index, column with timestamps.
        sensor_cols: Optional {label: column_name} for flag_true_* stats.
        motor_col: Optional column for hours_motor_runtime (e.g. supply_vfd_speed).
        period_range: Optional (start_ts, end_ts) for fault period (e.g. from flatline_period_range).
                      When provided, fault_period stats use this range so they match when you filter.

    Returns:
        Dict with total_days, total_hours, hours_fault_mode, percent_true/false,
        hours_motor_runtime (if motor_col), and flag_true_* for each sensor_col.
    """
    if timestamp_col and timestamp_col in df.columns:
        df = df.set_index(timestamp_col) if timestamp_col != df.index.name else df
    if not isinstance(df.index, pd.DatetimeIndex):
        return {"error": "DataFrame must have DatetimeIndex"}

    delta = df.index.to_series().diff()
    total_td = delta.sum()
    hours_fault = (delta * df[flag_col]).sum() / pd.Timedelta(hours=1)
    total_hours = total_td / pd.Timedelta(hours=1)

    summary = {
        "total_days": round(total_td / pd.Timedelta(days=1), 2),
        "total_hours": round(total_td / pd.Timedelta(hours=1)),
        f"hours_{flag_col.replace('_flag','')}_mode": round(hours_fault),
        "percent_true": round(df[flag_col].mean() * 100, 2),
        "percent_false": round((100 - df[flag_col].mean() * 100), 2),
        "percent_hours_true": round(100 * hours_fault / total_hours, 2) if total_hours > 0 else 0,
    }

    if motor_col and motor_col in df.columns:
        motor_on = df[motor_col].gt(0.01).astype(int)
        summary["hours_motor_runtime"] = round(
            (delta * motor_on).sum() / pd.Timedelta(hours=1), 2
        )

    if sensor_cols:
        fault_mask = df[flag_col] == 1
        for label, col in sensor_cols.items():
            if col in df.columns:
                if fault_mask.any():
                    summary[f"flag_true_{label}"] = round(
                        df.loc[fault_mask, col].mean(), 2
                    )
                else:
                    summary[f"flag_true_{label}"] = "N/A"

    # Fault-period stats: when filtered to fault time range, these numbers match
    fault_mask = df[flag_col] == 1
    if fault_mask.any():
        if period_range:
            start_ts, end_ts = period_range
        else:
            fault_times = df.index[fault_mask]
            start_ts = fault_times.min()
            end_ts = fault_times.max()
        period_td = end_ts - start_ts
        period_df = df.loc[start_ts:end_ts]
        period_rows = len(period_df)
        period_flagged = int(period_df[flag_col].sum())
        summary["fault_period_start"] = str(start_ts)
        summary["fault_period_end"] = str(end_ts)
        summary["fault_period_days"] = round(period_td / pd.Timedelta(days=1), 2)
        summary["fault_period_hours"] = round(period_td / pd.Timedelta(hours=1))
        summary["fault_period_rows"] = period_rows
        summary["fault_period_rows_flagged"] = period_flagged
        summary["fault_period_percent_true"] = (
            round(100 * period_flagged / period_rows, 2) if period_rows > 0 else 0
        )

    return summary


def summarize_all_faults(
    df: pd.DataFrame,
    flag_cols: Optional[List[str]] = None,
    motor_col: str = "supply_vfd_speed",
    sensor_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute analytics for all fault flag columns.

    Args:
        df: DataFrame with fault flags.
        flag_cols: List of flag column names. Default: all columns ending in _flag.
        motor_col: Column for motor runtime.
        sensor_map: Optional {flag_col: {label: col}} for flag_true_* per fault.

    Returns:
        Dict[flag_col, summary_dict]
    """
    if flag_cols is None:
        flag_cols = [c for c in df.columns if c.endswith("_flag") and c in df.columns]
    sensor_map = sensor_map or {}
    results = {}
    for fc in flag_cols:
        sensors = sensor_map.get(fc)
        results[fc] = summarize_fault(df, fc, sensor_cols=sensors, motor_col=motor_col)
    return results


def print_summary(summary: Dict[str, Any], title: Optional[str] = None) -> None:
    """Print summary dict in readable format."""
    if title:
        print(f"\n--- {title} ---")
    for k, v in summary.items():
        print(f"  {k.replace('_', ' ')}: {v}")


def analyze_flatline_episodes(
    df: pd.DataFrame,
    flag_col: str = "flatline_flag",
    timestamp_col: str = "timestamp",
    sensor_cols: Optional[Dict[str, str]] = None,
    tolerance: float = 0.000001,
) -> List[Dict[str, Any]]:
    """
    Find flatline episodes and which BRICK sensor(s) were flat in each.

    For each contiguous run of flatline_flag=1:
    - Which sensors had spread (max-min) < tolerance over the episode
    - all_sensors_flat: True if every sensor was flat (device offline)
    - single_sensor_flat: True if exactly one sensor was flat (e.g. controller not writing)

    Args:
        df: DataFrame with flatline_flag and sensor columns.
        flag_col: Flatline flag column name.
        timestamp_col: Timestamp column.
        sensor_cols: {BRICK_class: csv_column} e.g. {"Outside_Air_Temperature_Sensor": "OAT (°F)"}
        tolerance: Spread threshold for "flat" (same as flatline rule).

    Returns:
        List of episode dicts with start_ts, end_ts, sensors_flat (BRICK names),
        all_sensors_flat, single_sensor_flat.
    """
    sensor_cols = sensor_cols or {}
    faulted = df[df[flag_col] == 1]
    if faulted.empty:
        return []

    # Find contiguous episodes (runs of flag=1)
    flag = df[flag_col].astype(int)
    starts = (flag.diff() == 1) & (flag == 1)
    ends = (flag == 1) & (flag.shift(-1).fillna(0) == 0)
    start_idxs = df.index[starts].tolist()
    end_idxs = df.index[ends].tolist()
    if flag.iloc[0] == 1:
        start_idxs.insert(0, df.index[0])
    if flag.iloc[-1] == 1:
        end_idxs.append(df.index[-1])
    if len(start_idxs) != len(end_idxs):
        start_idxs = [faulted.index.min()]
        end_idxs = [faulted.index.max()]

    episodes = []
    for start_idx, end_idx in zip(start_idxs, end_idxs):
        ep_df = df.loc[start_idx:end_idx]
        start_ts = ep_df[timestamp_col].min()
        end_ts = ep_df[timestamp_col].max()
        sensors_flat: List[str] = []
        num_evaluated = 0
        for brick_name, col in sensor_cols.items():
            if col not in ep_df.columns:
                continue
            s = ep_df[col].dropna()
            if len(s) < 2:
                continue
            num_evaluated += 1
            spread = s.max() - s.min()
            if spread < tolerance:
                sensors_flat.append(brick_name)
        all_flat = num_evaluated > 0 and len(sensors_flat) == num_evaluated
        single_flat = len(sensors_flat) == 1
        episodes.append({
            "start_ts": start_ts,
            "end_ts": end_ts,
            "sensors_flat": sensors_flat,
            "all_sensors_flat": all_flat,
            "single_sensor_flat": single_flat,
            "rows": len(ep_df),
        })
    return episodes


def print_flatline_episodes(
    episodes: List[Dict[str, Any]],
    title: str = "Flatline episodes",
    max_show: Optional[int] = 10,
) -> None:
    """
    Print flatline episode analysis in BRICK format.

    Shows which sensor(s) were flat per episode and flags device-offline vs
    single-sensor-not-writing. If max_show is set, shows first and last N episodes.
    """
    print(f"\n--- {title} ---")
    if not episodes:
        print("  No flatline episodes.")
        return
    n = len(episodes)
    if max_show and n > max_show * 2:
        first = episodes[:max_show]
        last = episodes[-max_show:]
        print(f"  ({n} episodes total, showing first {max_show} and last {max_show})")
        for i, ep in enumerate(first, 1):
            _print_episode(i, ep)
        print(f"\n  ... ({n - max_show * 2} episodes omitted) ...")
        for i, ep in enumerate(last, n - max_show + 1):
            _print_episode(i, ep)
    else:
        for i, ep in enumerate(episodes, 1):
            _print_episode(i, ep)


def _print_episode(idx: int, ep: Dict[str, Any]) -> None:
    """Print a single episode in BRICK format."""
    print(f"\n  Episode {idx}: {ep['start_ts']} to {ep['end_ts']} ({ep['rows']} rows)")
    sensors = ep["sensors_flat"]
    print(f"    BRICK sensors flat: {', '.join(sensors) or '(none)'}")
    if ep["all_sensors_flat"]:
        print("    All sensors flat: Yes (device offline)")
    elif ep["single_sensor_flat"] and sensors:
        print(f"    Single sensor flat: {sensors[0]} (controller not writing)")


def analyze_bounds_episodes(
    df: pd.DataFrame,
    flag_col: str = "bad_sensor_flag",
    timestamp_col: str = "timestamp",
    sensor_cols: Optional[Dict[str, str]] = None,
    bounds_map: Optional[Dict[str, tuple]] = None,
) -> List[Dict[str, Any]]:
    """
    Find bounds-violation episodes and which BRICK sensor(s) were out of range in each.

    For each contiguous run of flag=1:
    - Which sensors had any value outside [low, high] in that episode
    - all_sensors_oob: True if every sensor was out of bounds
    - single_sensor_oob: True if exactly one sensor was out of bounds

    Args:
        df: DataFrame with flag and sensor columns.
        flag_col: Bounds flag column name.
        timestamp_col: Timestamp column.
        sensor_cols: {BRICK_class: csv_column} e.g. {"Supply_Air_Temperature_Sensor": "SAT (°F)"}
        bounds_map: {BRICK_class: (low, high)} for each sensor. Must match units in data.

    Returns:
        List of episode dicts with start_ts, end_ts, sensors_oob (BRICK names),
        all_sensors_oob, single_sensor_oob.
    """
    sensor_cols = sensor_cols or {}
    bounds_map = bounds_map or {}
    faulted = df[df[flag_col] == 1]
    if faulted.empty:
        return []

    # Find contiguous episodes (runs of flag=1)
    flag = df[flag_col].astype(int)
    starts = (flag.diff() == 1) & (flag == 1)
    ends = (flag == 1) & (flag.shift(-1).fillna(0) == 0)
    start_idxs = df.index[starts].tolist()
    end_idxs = df.index[ends].tolist()
    if flag.iloc[0] == 1:
        start_idxs.insert(0, df.index[0])
    if flag.iloc[-1] == 1:
        end_idxs.append(df.index[-1])
    if len(start_idxs) != len(end_idxs):
        start_idxs = [faulted.index.min()]
        end_idxs = [faulted.index.max()]

    episodes = []
    for start_idx, end_idx in zip(start_idxs, end_idxs):
        ep_df = df.loc[start_idx:end_idx]
        start_ts = ep_df[timestamp_col].min()
        end_ts = ep_df[timestamp_col].max()
        sensors_oob: List[str] = []
        sensor_means: Dict[str, float] = {}
        for brick_name, col in sensor_cols.items():
            if col not in ep_df.columns:
                continue
            b = bounds_map.get(brick_name)
            if not b or len(b) != 2:
                continue
            low, high = float(b[0]), float(b[1])
            s = ep_df[col].dropna()
            if s.empty:
                continue
            if (s < low).any() or (s > high).any():
                sensors_oob.append(brick_name)
                sensor_means[brick_name] = round(float(s.mean()), 2)
        num_with_bounds = sum(1 for k in sensor_cols if bounds_map.get(k) and len(bounds_map.get(k)) == 2)
        all_oob = num_with_bounds > 0 and len(sensors_oob) == num_with_bounds
        single_oob = len(sensors_oob) == 1
        episodes.append({
            "start_ts": start_ts,
            "end_ts": end_ts,
            "sensors_flat": sensors_oob,  # reuse key for print compatibility
            "all_sensors_flat": all_oob,
            "single_sensor_flat": single_oob,
            "rows": len(ep_df),
            "sensor_means": sensor_means,
        })
    return episodes


def print_bounds_episodes(
    episodes: List[Dict[str, Any]],
    title: str = "Bounds episodes",
    max_show: Optional[int] = 10,
) -> None:
    """
    Print bounds episode analysis in BRICK format.

    Shows which sensor(s) were out of bounds per episode. If max_show is set,
    shows first and last N episodes.
    """
    print(f"\n--- {title} ---")
    if not episodes:
        print("  No bounds episodes.")
        return
    n = len(episodes)
    if max_show and n > max_show * 2:
        first = episodes[:max_show]
        last = episodes[-max_show:]
        print(f"  ({n} episodes total, showing first {max_show} and last {max_show})")
        for i, ep in enumerate(first, 1):
            _print_bounds_episode(i, ep)
        print(f"\n  ... ({n - max_show * 2} episodes omitted) ...")
        for i, ep in enumerate(last, n - max_show + 1):
            _print_bounds_episode(i, ep)
    else:
        for i, ep in enumerate(episodes, 1):
            _print_bounds_episode(i, ep)


def _print_bounds_episode(idx: int, ep: Dict[str, Any]) -> None:
    """Print a single bounds episode in BRICK format."""
    print(f"\n  Episode {idx}: {ep['start_ts']} to {ep['end_ts']} ({ep['rows']} rows)")
    sensors = ep["sensors_flat"]
    print(f"    BRICK sensors out of bounds: {', '.join(sensors) or '(none)'}")
    means = ep.get("sensor_means", {})
    if means:
        avg_str = ", ".join(f"{k}: {v}" for k, v in means.items())
        print(f"    Avg readings: {avg_str}")
    if ep["all_sensors_flat"]:
        print("    All sensors OOB: Yes")
    elif ep["single_sensor_flat"] and sensors:
        print(f"    Single sensor OOB: {sensors[0]}")
