"""PID-HUNT-1 — suspected control-output hunting (0–100% analog commands)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PidHuntingParams:
    window: str = "1h"
    change_deadband_pct: float = 1.0
    minimum_span_pct: float = 20.0
    total_variation_fault_pct: float = 500.0
    minimum_equivalent_cycles: float = 2.5
    minimum_reversals: int = 4
    minimum_coverage_pct: float = 80.0
    low_extreme_pct: float = 10.0
    high_extreme_pct: float = 90.0


def _infer_interval(index: pd.DatetimeIndex, poll_seconds: float | None) -> pd.Timedelta:
    if poll_seconds is not None and poll_seconds > 0:
        return pd.Timedelta(seconds=float(poll_seconds))
    if len(index) < 2:
        return pd.Timedelta(minutes=1)
    diffs = pd.Series(index).diff().dropna()
    med = diffs.median()
    if pd.isna(med) or med <= pd.Timedelta(0):
        return pd.Timedelta(minutes=1)
    return pd.Timedelta(med)


def to_percent_output(series: pd.Series) -> pd.Series:
    """Normalize a command/position series to 0–100%."""
    s = pd.to_numeric(series, errors="coerce")
    finite = s.dropna()
    if finite.empty:
        return s
    # Values already on 0–1 fraction → scale to percent.
    if float(finite.quantile(0.95)) <= 1.5:
        s = s * 100.0
    return s.clip(lower=0.0, upper=100.0)


def hunting_fault_mask(
    output_pct: pd.Series,
    *,
    params: PidHuntingParams = PidHuntingParams(),
    poll_seconds: float | None = None,
    enabled: pd.Series | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """
    Rolling one-hour suspected hunting metrics for a 0–100% control output.

    Returns (fault_mask, metrics_frame) aligned to ``output_pct.index``.
    """
    if not isinstance(output_pct.index, pd.DatetimeIndex):
        raise ValueError("output_pct must have a DatetimeIndex")

    output = to_percent_output(output_pct).sort_index()
    interval = _infer_interval(output.index, poll_seconds)
    window = pd.Timedelta(params.window)
    if interval <= pd.Timedelta(0):
        raise ValueError("sample interval must be positive")

    expected_samples = max(2, int(window / interval))
    minimum_samples = max(
        2,
        int(np.ceil(expected_samples * params.minimum_coverage_pct / 100.0)),
    )

    valid = output.notna()
    raw_delta = output.diff()
    significant_delta = raw_delta.where(
        raw_delta.abs() >= params.change_deadband_pct,
        0.0,
    )

    total_variation = significant_delta.abs().rolling(
        window,
        min_periods=minimum_samples,
    ).sum()

    rolling_min = output.rolling(window, min_periods=minimum_samples).min()
    rolling_max = output.rolling(window, min_periods=minimum_samples).max()
    output_span = rolling_max - rolling_min

    direction = pd.Series(
        np.sign(significant_delta.to_numpy(dtype="float64")),
        index=significant_delta.index,
        dtype="float64",
    ).replace(0.0, np.nan)
    previous_direction = direction.ffill().shift(1)
    reversal_event = (
        direction.notna()
        & previous_direction.notna()
        & direction.ne(previous_direction)
    ).astype("int64")
    reversals = reversal_event.rolling(window, min_periods=minimum_samples).sum()

    valid_samples = valid.astype("int64").rolling(window, min_periods=1).sum()
    coverage_pct = (100.0 * valid_samples / float(expected_samples)).clip(upper=100.0)

    equivalent_cycles = total_variation / (2.0 * output_span.replace(0.0, np.nan))

    low_extreme_seen = (
        output.le(params.low_extreme_pct)
        .astype("int64")
        .rolling(window, min_periods=minimum_samples)
        .max()
        .fillna(0)
        .astype(bool)
    )
    high_extreme_seen = (
        output.ge(params.high_extreme_pct)
        .astype("int64")
        .rolling(window, min_periods=minimum_samples)
        .max()
        .fillna(0)
        .astype(bool)
    )

    if enabled is None:
        loop_enabled = pd.Series(True, index=output.index)
    else:
        loop_enabled = (
            pd.to_numeric(enabled.reindex(output.index), errors="coerce")
            .fillna(0)
            .gt(0)
        )

    fault = (
        loop_enabled
        & coverage_pct.ge(params.minimum_coverage_pct)
        & output_span.ge(params.minimum_span_pct)
        & total_variation.ge(params.total_variation_fault_pct)
        & equivalent_cycles.ge(params.minimum_equivalent_cycles)
        & reversals.ge(params.minimum_reversals)
    ).fillna(False)

    metrics = pd.DataFrame(
        {
            "control-output-pct": output,
            "total_variation_1h": total_variation,
            "output_min_1h": rolling_min,
            "output_max_1h": rolling_max,
            "output_span_1h": output_span,
            "equivalent_cycles_1h": equivalent_cycles,
            "reversals_1h": reversals,
            "coverage_pct_1h": coverage_pct,
            "low_extreme_seen_1h": low_extreme_seen,
            "high_extreme_seen_1h": high_extreme_seen,
            "loop-enabled": loop_enabled,
            "fault": fault,
        },
        index=output.index,
    )
    return fault.astype(bool), metrics


def _looks_like_ao_column(name: str) -> bool:
    """True when a raw historian column name is likely a 0–100% command/position."""
    from app.rules.cookbook_catalog import _CONTROL_OUTPUT_COL_EXCLUDE

    cl = str(name).lower()
    if any(x in cl for x in _CONTROL_OUTPUT_COL_EXCLUDE):
        return False
    # Trailing / embedded setpoint markers (avoid matching `_speed`)
    if cl.endswith("_sp") or "_sp_" in cl or cl.endswith("setpoint"):
        return False
    if cl.endswith("_rh") or cl.startswith("rh_") or "_rh_" in cl:
        return False
    # Explicit AO-ish tokens (commands / valve / damper / speed %)
    tokens = (
        "valve",
        "damper",
        "actuator",
        "fan_speed",
        "fan-cmd",
        "pump-cmd",
        "pump_speed",
        "vfd",
        "reheat",
        "chw_valve",
        "hw_valve",
        "clg_valve",
        "htg_valve",
        "oa_damper",
        "ex_dmpr",
        "mad_c",
        "dmpr",
    )
    if not any(t in cl for t in tokens):
        return False
    # Prefer cmd/pos/pct/speed columns; skip binary status-looking names without pct/speed
    if any(x in cl for x in ("_pct", "percent", "speed", "cmd", "pos", "position", "valve")):
        return True
    return "damper" in cl or "actuator" in cl


def iter_control_output_series(df: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    """Mapped CONTROL_OUTPUT_ROLES first, then unmatched raw AO-like columns.

    Does **not** use a point named ``Loop`` — only role-mapped AOs and column heuristics
    for valve / damper / fan / pump commands.
    """
    from app.rules.cookbook_catalog import CONTROL_OUTPUT_ROLES

    out: list[tuple[str, pd.Series]] = []
    seen_cols: set[str] = set()
    for role in CONTROL_OUTPUT_ROLES:
        if role not in df.columns or df[role].notna().sum() == 0:
            continue
        out.append((role, df[role]))
        seen_cols.add(role)
        # Role column may be a copy of a source column with the same values; track attrs
        src = df.attrs.get("role_sources", {}).get(role) if hasattr(df, "attrs") else None
        if isinstance(src, str):
            seen_cols.add(src)

    for col in df.columns:
        if col in seen_cols or col in CONTROL_OUTPUT_ROLES:
            continue
        if not _looks_like_ao_column(str(col)):
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().sum() == 0:
            continue
        # Skip near-boolean 0/1 status (not a modulating AO)
        finite = s.dropna()
        if finite.empty:
            continue
        uniq = set(np.round(finite.unique(), 6).tolist())
        if uniq <= {0.0, 1.0} and float(finite.max()) <= 1.0:
            continue
        out.append((f"col:{col}", s))
    return out


def control_outputs_present(df: pd.DataFrame) -> bool:
    return bool(iter_control_output_series(df))
