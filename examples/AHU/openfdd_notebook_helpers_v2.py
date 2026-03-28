
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd
from open_fdd.engine import RuleRunner
from open_fdd.reports import (
    summarize_all_faults,
    analyze_bounds_episodes,
    analyze_flatline_episodes,
)


def load_dataset(
    csv_path: Path,
    timestamp_source_col: str,
    timestamp_col: str,
    timestamp_format: Optional[str] = None,
    timezone_suffix_regex: Optional[str] = None,
) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    ts_clean = df[timestamp_source_col].astype(str)
    if timezone_suffix_regex:
        ts_clean = ts_clean.str.replace(timezone_suffix_regex, "", regex=True)
    df[timestamp_col] = pd.to_datetime(ts_clean, format=timestamp_format, errors="raise")
    df = df.sort_values(timestamp_col).reset_index(drop=True)
    return df


def run_openfdd(
    df: pd.DataFrame,
    rules_dir: Path,
    timestamp_col: str,
    column_map: Dict[str, str],
) -> pd.DataFrame:
    runner = RuleRunner(rules_path=rules_dir)
    return runner.run(
        df,
        timestamp_col=timestamp_col,
        column_map=column_map,
        skip_missing_columns=True,
    )


def get_flag_cols(df_result: pd.DataFrame) -> list[str]:
    return [c for c in df_result.columns if c.endswith("_flag")]


def summarize_flags(df_result: pd.DataFrame, flag_cols: Iterable[str]) -> pd.DataFrame:
    return (
        df_result[list(flag_cols)]
        .sum()
        .sort_values(ascending=False)
        .rename("fault_count")
        .to_frame()
    )


def add_direct_bounds_flags(
    df_result: pd.DataFrame,
    bounds_map: Dict[str, Tuple[float, float]],
    suffix: str = "_bounds_fault",
) -> tuple[pd.DataFrame, list[str]]:
    created_cols: list[str] = []
    for col, (low, high) in bounds_map.items():
        out_col = f"{col}{suffix}"
        df_result[out_col] = ((df_result[col] < low) | (df_result[col] > high)).astype(int)
        created_cols.append(out_col)
    return df_result, created_cols


def summarize_bad_sensors(df_result: pd.DataFrame, bad_cols: Iterable[str]) -> pd.DataFrame:
    return (
        df_result[list(bad_cols)]
        .sum()
        .sort_values(ascending=False)
        .rename("bad_count")
        .to_frame()
    )


def shade_flag_windows(ax, time_series: pd.Series, flag_series: pd.Series, alpha: float = 0.18):
    in_fault = False
    start_time = None
    for i in range(len(flag_series)):
        active = bool(flag_series.iloc[i])
        if active and not in_fault:
            in_fault = True
            start_time = time_series.iloc[i]
        elif not active and in_fault:
            end_time = time_series.iloc[i]
            ax.axvspan(start_time, end_time, alpha=alpha)
            in_fault = False
    if in_fault:
        ax.axvspan(start_time, time_series.iloc[-1], alpha=alpha)


def plot_series_with_fault_shading(
    df_result: pd.DataFrame,
    timestamp_col: str,
    series_cols: Iterable[str],
    fault_flag_col: Optional[str],
    title: str,
    ylabel: str,
    figsize=(16, 6),
    shade_alpha: float = 0.18,
):
    fig, ax = plt.subplots(figsize=figsize)
    for col in series_cols:
        ax.plot(df_result[timestamp_col], df_result[col], label=col)
    if fault_flag_col and fault_flag_col in df_result.columns:
        shade_flag_windows(ax, df_result[timestamp_col], df_result[fault_flag_col], alpha=shade_alpha)
    ax.set_title(title)
    ax.set_xlabel("Timestamp")
    ax.set_ylabel(ylabel)
    ax.legend()
    plt.show()


def _sensor_fault_col(sensor_col: str, suffix: str = "_bounds_fault") -> str:
    return f"{sensor_col}{suffix}"


def plot_sensor_with_bad_windows(
    df_result: pd.DataFrame,
    timestamp_col: str,
    sensor_col: str,
    fault_suffix: str = "_bounds_fault",
    figsize=(16, 4),
    shade_alpha: float = 0.18,
):
    bad_col = _sensor_fault_col(sensor_col, fault_suffix)
    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(df_result[timestamp_col], df_result[sensor_col], label=sensor_col)
    shade_flag_windows(ax, df_result[timestamp_col], df_result[bad_col], alpha=shade_alpha)
    ax.set_title(f"{sensor_col} with Shaded Fault Windows")
    ax.set_xlabel("Timestamp")
    ax.set_ylabel(sensor_col)
    ax.legend()
    plt.show()


def plot_sensor_with_openfdd_overlap(
    df_result: pd.DataFrame,
    timestamp_col: str,
    sensor_col: str,
    fault_flag_col: str = "bad_sensor_flag",
    fault_suffix: str = "_bounds_fault",
    figsize=(16, 4),
    shade_alpha: float = 0.18,
):
    bad_col = _sensor_fault_col(sensor_col, fault_suffix)
    combined_flag = ((df_result[fault_flag_col] == 1) & (df_result[bad_col] == 1)).astype(int)
    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(df_result[timestamp_col], df_result[sensor_col], label=sensor_col)
    shade_flag_windows(ax, df_result[timestamp_col], combined_flag, alpha=shade_alpha)
    ax.set_title(f"{sensor_col} with Open-FDD Bad Sensor Overlap Shaded")
    ax.set_xlabel("Timestamp")
    ax.set_ylabel(sensor_col)
    ax.legend()
    plt.show()


def compute_fan_runtime(
    df_result: pd.DataFrame,
    timestamp_col: str,
    fan_status_col: str,
    fan_output_col: str,
    fan_output_threshold: float,
    max_gap_hours: float | None = 2.0,
) -> tuple[pd.DataFrame, str, float]:
    """
    Each row owns the interval until the next timestamp.
    Runtime is computed from the forward interval.
    """
    df_result = df_result.sort_values(timestamp_col).reset_index(drop=True).copy()

    dt_forward = (
        df_result[timestamp_col].shift(-1) - df_result[timestamp_col]
    ).dt.total_seconds() / 3600.0

    typical_step = float(dt_forward.dropna().median()) if len(dt_forward.dropna()) > 0 else 0.0

    df_result["dt_hours"] = dt_forward.fillna(typical_step).clip(lower=0)
    if max_gap_hours is not None:
        df_result["dt_hours"] = df_result["dt_hours"].clip(upper=max_gap_hours)

    status_available = (
        fan_status_col in df_result.columns
        and df_result[fan_status_col].notna().any()
    )
    output_available = (
        fan_output_col in df_result.columns
        and df_result[fan_output_col].notna().any()
    )

    if status_available:
        raw_status = df_result[fan_status_col].copy()
        status_num = pd.to_numeric(raw_status, errors="coerce")
        status_text = raw_status.astype(str).str.strip().str.lower()

        status_bool = (
            (status_num > 0)
            | status_text.isin(["on", "true", "yes", "running", "enable", "enabled"])
        )

        missing_mask = raw_status.isna() | raw_status.astype(str).str.strip().eq("")
        status_bool = status_bool.mask(missing_mask)

        df_result["fan_on"] = status_bool.ffill().fillna(False).astype(bool)
        fan_logic_used = f"{fan_status_col} parsed as numeric/text status, forward-filled"

    elif output_available:
        output_num = pd.to_numeric(df_result[fan_output_col], errors="coerce")
        output_bool = (output_num > fan_output_threshold).mask(output_num.isna())

        df_result["fan_on"] = output_bool.ffill().fillna(False).astype(bool)
        fan_logic_used = f"{fan_output_col} > {fan_output_threshold}, forward-filled"

    else:
        df_result["fan_on"] = False
        fan_logic_used = "No usable fan status/output column found"

    df_result["fan_run_hours"] = df_result["fan_on"].astype(float) * df_result["dt_hours"]
    total_fan_run_hours = float(df_result["fan_run_hours"].sum())
    return df_result, fan_logic_used, total_fan_run_hours


def weekly_fan_runtime(df_result: pd.DataFrame, timestamp_col: str) -> pd.Series:
    return (
        df_result.set_index(timestamp_col)["fan_run_hours"]
        .resample("W")
        .sum()
    )


def plot_weekly_fan_runtime(weekly_fan_hours: pd.Series, title: str, figsize=(16, 6)):
    fig, ax = plt.subplots(figsize=figsize)
    weekly_fan_hours.plot(kind="bar", ax=ax)
    ax.set_title(title)
    ax.set_xlabel("Week Ending")
    ax.set_ylabel("Fan Run Hours")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.show()


def plot_fault_pies(df_result: pd.DataFrame, fault_flag_col: str, title_prefix: str):
    if fault_flag_col not in df_result.columns:
        print(f"{fault_flag_col} not found.")
        return

    fault_flag = df_result[fault_flag_col].fillna(0).astype(float) > 0
    fan_on = df_result["fan_on"].fillna(False)
    runtime_hours = df_result["fan_run_hours"].fillna(0)
    interval_hours = df_result["dt_hours"].fillna(0)

    runtime_during_fault = runtime_hours.loc[fault_flag].sum()
    runtime_without_fault = runtime_hours.loc[~fault_flag].sum()

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.pie(
        [runtime_during_fault, runtime_without_fault],
        labels=["Fan Runtime During Fault", "Fan Runtime Without Fault"],
        autopct="%1.1f%%",
        startangle=90,
    )
    ax.set_title(f"{title_prefix}: Percent of Fan Runtime During Fault vs No Fault")
    plt.show()

    fault_time_fan_on = interval_hours.loc[fault_flag & fan_on].sum()
    fault_time_fan_off = interval_hours.loc[fault_flag & (~fan_on)].sum()

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.pie(
        [fault_time_fan_on, fault_time_fan_off],
        labels=["Fault Time While Fan On", "Fault Time While Fan Off"],
        autopct="%1.1f%%",
        startangle=90,
    )
    ax.set_title(f"{title_prefix}: Percent of Fault Time with Fan On vs Off")
    plt.show()


def plot_sensor_fault_pies(
    df_result: pd.DataFrame,
    sensor_col: str,
    rule_name: str = "Bounds",
    fault_suffix: str = "_bounds_fault",
    bounds_map: Optional[Dict[str, Tuple[float, float]]] = None,
):
    fault_col = _sensor_fault_col(sensor_col, fault_suffix)
    if fault_col not in df_result.columns:
        print(f"{fault_col} not found.")
        return

    fault_flag = df_result[fault_col].fillna(0).astype(float) > 0
    fan_on = df_result["fan_on"].fillna(False)
    runtime_hours = df_result["fan_run_hours"].fillna(0)
    interval_hours = df_result["dt_hours"].fillna(0)

    title_suffix = ""
    if bounds_map is not None and sensor_col in bounds_map and rule_name.lower() == "bounds":
        low, high = bounds_map[sensor_col]
        title_suffix = f" [{low}, {high}]"

    title_prefix = f"{sensor_col} - {rule_name}{title_suffix}"

    runtime_during_fault = runtime_hours.loc[fault_flag].sum()
    runtime_without_fault = runtime_hours.loc[~fault_flag].sum()

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.pie(
        [runtime_during_fault, runtime_without_fault],
        labels=[
            f"{sensor_col} fault while fan running",
            f"{sensor_col} normal while fan running",
        ],
        autopct="%1.1f%%",
        startangle=90,
    )
    ax.set_title(f"{title_prefix}: Percent of Fan Runtime During Fault")
    plt.show()

    fault_time_fan_on = interval_hours.loc[fault_flag & fan_on].sum()
    fault_time_fan_off = interval_hours.loc[fault_flag & (~fan_on)].sum()

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.pie(
        [fault_time_fan_on, fault_time_fan_off],
        labels=[
            f"{sensor_col} fault with fan on",
            f"{sensor_col} fault with fan off",
        ],
        autopct="%1.1f%%",
        startangle=90,
    )
    ax.set_title(f"{title_prefix}: Percent of Fault Time with Fan On vs Off")
    plt.show()


def report_outputs(
    df_result: pd.DataFrame,
    flag_cols: Iterable[str],
    report_motor_col: str,
    column_map: Dict[str, str],
    timestamp_col: str,
    bounds_map: Dict[str, Tuple[float, float]],
    flatline_flag: str,
    flatline_tolerance: float = 1e-6,
):
    sensor_map_for_reports = {flag: column_map for flag in flag_cols}
    summary = summarize_all_faults(
        df_result,
        flag_cols=list(flag_cols),
        motor_col=report_motor_col,
        sensor_map=sensor_map_for_reports,
    )
    summary_df = pd.DataFrame(summary).T

    bounds_df = pd.DataFrame()
    if "bad_sensor_flag" in df_result.columns:
        bounds_eps = analyze_bounds_episodes(
            df_result,
            flag_col="bad_sensor_flag",
            timestamp_col=timestamp_col,
            sensor_cols=column_map,
            bounds_map=bounds_map,
        )
        bounds_df = pd.DataFrame(bounds_eps)

    flatline_df = pd.DataFrame()
    if flatline_flag in df_result.columns:
        flatline_eps = analyze_flatline_episodes(
            df_result,
            flag_col=flatline_flag,
            timestamp_col=timestamp_col,
            sensor_cols=column_map,
            tolerance=flatline_tolerance,
        )
        flatline_df = pd.DataFrame(flatline_eps)

    return summary_df, bounds_df, flatline_df
