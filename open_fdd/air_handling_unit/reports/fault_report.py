"""
Fault analytics and reporting for config-driven FDD.

Provides fault duration, motor runtime, and sensor stats when faults occur.
"""

from typing import Any, Dict, List, Optional

import pandas as pd


def summarize_fault(
    df: pd.DataFrame,
    flag_col: str,
    timestamp_col: Optional[str] = None,
    sensor_cols: Optional[Dict[str, str]] = None,
    motor_col: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute fault analytics for a single fault flag.

    Args:
        df: DataFrame with datetime index or timestamp_col.
        flag_col: Name of fault flag column (0/1).
        timestamp_col: If df has no datetime index, column with timestamps.
        sensor_cols: Optional {label: column_name} for flag_true_* stats.
        motor_col: Optional column for hours_motor_runtime (e.g. supply_vfd_speed).

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

    summary = {
        "total_days": round(total_td / pd.Timedelta(days=1), 2),
        "total_hours": round(total_td / pd.Timedelta(hours=1)),
        f"hours_{flag_col.replace('_flag','')}_mode": round(
            (delta * df[flag_col]).sum() / pd.Timedelta(hours=1)
        ),
        "percent_true": round(df[flag_col].mean() * 100, 2),
        "percent_false": round((100 - df[flag_col].mean() * 100), 2),
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
                summary[f"flag_true_{label}"] = round(
                    df.loc[fault_mask, col].mean(), 2
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
        results[fc] = summarize_fault(
            df, fc, sensor_cols=sensors, motor_col=motor_col
        )
    return results


def print_summary(summary: Dict[str, Any], title: Optional[str] = None) -> None:
    """Print summary dict in readable format."""
    if title:
        print(f"\n--- {title} ---")
    for k, v in summary.items():
        print(f"  {k.replace('_', ' ')}: {v}")
