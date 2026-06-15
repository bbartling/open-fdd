"""Historian freshness and post-threshold timing for Bench 5007 smoke reports."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pyarrow as pa


def expected_confirmation_delay_seconds(
    *,
    confirmation_minutes: float,
    confirmation_rows: int,
    poll_seconds: int,
) -> float:
    return max(float(confirmation_minutes) * 60.0, int(confirmation_rows) * int(poll_seconds))


def parse_ts(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def timestamp_interval_stats(timestamps: pa.Array | pa.ChunkedArray) -> dict[str, float | None]:
    parsed = sorted(t for t in (parse_ts(x) for x in timestamps.to_pylist()) if t is not None)
    if len(parsed) < 2:
        return {"average_interval_s": None, "max_gap_s": None}
    gaps = [(parsed[i] - parsed[i - 1]).total_seconds() for i in range(1, len(parsed))]
    return {
        "average_interval_s": sum(gaps) / len(gaps),
        "max_gap_s": max(gaps),
    }


def classify_historian_mode(
    *,
    synthetic: bool,
    dry_run: bool,
    live: bool,
    data_is_fresh: bool,
    data_window_matches_run_window: bool,
) -> str:
    if synthetic:
        return "synthetic"
    if dry_run:
        return "dry_run"
    if live and data_is_fresh and data_window_matches_run_window:
        return "live_recent"
    if live:
        return "historical_replay"
    return "unknown"


def assess_data_freshness(
    *,
    first_sample_time: str,
    last_sample_time: str,
    wall_clock_start: str,
    wall_clock_end: str,
    freshness_window_minutes: float,
    poll_seconds: int,
) -> dict[str, Any]:
    """Compare historian sample window to wall-clock smoke run."""
    w_start = parse_ts(wall_clock_start)
    w_end = parse_ts(wall_clock_end) or datetime.now(timezone.utc)
    d_start = parse_ts(first_sample_time)
    d_end = parse_ts(last_sample_time)
    window = timedelta(minutes=max(1.0, freshness_window_minutes))
    poll_tol = timedelta(seconds=max(15, int(poll_seconds) * 2))

    data_age_seconds: float | None = None
    data_is_fresh = False
    data_window_matches_run_window = False

    if d_end and w_end:
        data_age_seconds = max(0.0, (w_end - d_end).total_seconds())

    if d_start and d_end and w_start and w_end:
        overlap = d_start <= (w_end + poll_tol) and d_end >= (w_start - poll_tol)
        ends_near_run = d_end >= (w_end - window)
        starts_near_run = d_start >= (w_start - window)
        data_window_matches_run_window = overlap and ends_near_run
        data_is_fresh = data_window_matches_run_window and starts_near_run
        if data_age_seconds is not None:
            data_is_fresh = data_is_fresh and data_age_seconds <= window.total_seconds() + poll_tol.total_seconds()

    return {
        "data_window_start": first_sample_time,
        "data_window_end": last_sample_time,
        "wall_clock_start": wall_clock_start,
        "wall_clock_end": wall_clock_end,
        "data_is_fresh": data_is_fresh,
        "data_age_seconds": data_age_seconds,
        "data_window_matches_run_window": data_window_matches_run_window,
        "freshness_window_minutes": freshness_window_minutes,
    }


def describe_staleness(
    *,
    first_sample_time: str,
    last_sample_time: str,
    wall_clock_start: str,
    wall_clock_end: str,
    freshness_window_minutes: float,
    poll_seconds: int,
    origin: str = "",
    time_filter_relaxed: bool = False,
) -> dict[str, Any]:
    """Human-readable staleness diagnosis for strict-live smoke and API responses."""
    freshness = assess_data_freshness(
        first_sample_time=first_sample_time,
        last_sample_time=last_sample_time,
        wall_clock_start=wall_clock_start,
        wall_clock_end=wall_clock_end,
        freshness_window_minutes=freshness_window_minutes,
        poll_seconds=poll_seconds,
    )
    reasons: list[str] = []
    if origin == "demo":
        reasons.append("demo_historian_fallback")
    if time_filter_relaxed:
        reasons.append("time_filter_relaxed_full_stale_table")
    if not freshness.get("data_is_fresh"):
        if not freshness.get("data_window_matches_run_window"):
            reasons.append("no_timestamp_overlap_with_run_window")
        age = freshness.get("data_age_seconds")
        if age is not None and age > freshness_window_minutes * 60:
            reasons.append("data_age_exceeded")

    parts: list[str] = []
    if origin:
        parts.append(f"origin={origin}")
    if time_filter_relaxed:
        parts.append("time_filter_relaxed=true")
    if last_sample_time:
        parts.append(f"last_sample={last_sample_time}")
    if freshness.get("data_age_seconds") is not None:
        parts.append(f"data_age_s={int(freshness['data_age_seconds'])}")
    if reasons:
        parts.append(f"reasons={','.join(reasons)}")

    return {
        **freshness,
        "origin": origin,
        "time_filter_relaxed": time_filter_relaxed,
        "staleness_reasons": reasons,
        "summary": "; ".join(parts) if parts else "fresh",
    }


def infer_timing_validation_method(
    *,
    historian_mode: str,
    data_is_fresh: bool,
    threshold_change_row_index: int | None,
) -> str:
    if historian_mode == "synthetic":
        return "row_index_replay"
    if data_is_fresh:
        return "wall_clock"
    if historian_mode == "historical_replay" and threshold_change_row_index is not None:
        return "row_index_replay"
    if historian_mode == "historical_replay":
        return "wall_clock_unavailable"
    return "unknown"


def compute_post_change_timing(
    timestamps: pa.Array | pa.ChunkedArray,
    raw_mask: pa.Array | pa.ChunkedArray,
    confirmed_mask: pa.Array | pa.ChunkedArray,
    *,
    threshold_change_wall: datetime | None,
    threshold_change_row_index: int | None,
    expected_confirmation_delay_seconds: float,
    confirmation_rows: int,
) -> dict[str, Any]:
    """Fault timing relative to threshold change (wall-clock or row-index replay)."""
    ts_list = timestamps.to_pylist()
    raw_list = raw_mask.to_pylist()
    conf_list = confirmed_mask.to_pylist()
    n = min(len(ts_list), len(raw_list), len(conf_list))

    change_row = threshold_change_row_index
    change_sample_time = ""
    if threshold_change_row_index is not None and 0 <= threshold_change_row_index < n:
        change_sample_time = str(ts_list[threshold_change_row_index])
    elif threshold_change_wall is not None:
        for i in range(n):
            ts = parse_ts(ts_list[i])
            if ts and ts >= threshold_change_wall:
                change_row = i
                change_sample_time = str(ts_list[i])
                break

    preexisting_raw_fault = False
    first_raw_before = ""
    if change_row is not None:
        for i in range(change_row):
            if raw_list[i] is True:
                preexisting_raw_fault = True
                first_raw_before = str(ts_list[i])
                break
    else:
        for i in range(n):
            if raw_list[i] is True:
                preexisting_raw_fault = True
                first_raw_before = str(ts_list[i])
                break

    start_idx = change_row if change_row is not None else 0
    first_raw_after = ""
    first_confirmed_after = ""
    for i in range(start_idx, n):
        if raw_list[i] is True and not first_raw_after:
            first_raw_after = str(ts_list[i])
        if conf_list[i] is True and not first_confirmed_after:
            first_confirmed_after = str(ts_list[i])
            break

    observed_delay: float | None = None
    t_raw = parse_ts(first_raw_after)
    t_conf = parse_ts(first_confirmed_after)
    if t_raw and t_conf:
        observed_delay = (t_conf - t_raw).total_seconds()

    early_confirmed = False
    if first_confirmed_after:
        t_change = parse_ts(change_sample_time) or threshold_change_wall
        t_confirmed = parse_ts(first_confirmed_after)
        if t_change and t_confirmed:
            early_confirmed = (t_confirmed - t_change).total_seconds() < expected_confirmation_delay_seconds * 0.9
        elif change_row is not None:
            conf_idx = next((i for i in range(n) if conf_list[i] is True), None)
            if conf_idx is not None and (conf_idx - change_row + 1) < max(1, confirmation_rows):
                early_confirmed = True

    return {
        "threshold_change_wall_time": threshold_change_wall.isoformat() if threshold_change_wall else "",
        "threshold_change_sample_time": change_sample_time,
        "threshold_change_row_index": change_row,
        "preexisting_raw_fault": preexisting_raw_fault,
        "first_raw_fault_before_change": first_raw_before,
        "first_raw_fault_after_change": first_raw_after,
        "first_confirmed_fault_after_change": first_confirmed_after,
        "expected_confirmation_delay_seconds": expected_confirmation_delay_seconds,
        "observed_confirmation_delay_seconds": observed_delay,
        "early_confirmed_fault": early_confirmed,
    }
