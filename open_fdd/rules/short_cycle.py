"""SHORT-CYCLE (#1781): boiler / compressor short cycling from proven run status, the pandas twin of
``sql/fdd/postgres/rules/short_cycle.sql`` (same proof pick, duty classes, cycle rule, trailing-hour counts).

A status sample is the on-fraction (duty) of its interval: NF resamples a 0/1 status by AVERAGE, so a coarse bucket
holds a duty, never a max. Duty <= 0.05 is off, >= 0.95 is on for the whole interval, anything between is a partial
sample that must hold a start or a stop. Starts are the fewest consistent with the duties. All times are seconds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from open_fdd.analytics.runtime_intervals import ELAPSED_MAX_GAP_SECONDS

MECH_AMPS_MIN = 5.0       # A   (sql/fdd/runtime_defaults.json MECH_AMPS_MIN)
MECH_POWER_KW_MIN = 1.0   # kW  (MECH_POWER_KW_MIN)
#: proof candidates in order (Haystack role, on-threshold for analog proofs or None for a status read as a duty)
PROOF_CANDIDATES = (("boiler_operating_status", None), ("compressor_operating_status", None), ("chiller_operating_status", None),
                    ("chiller_electric_current", MECH_AMPS_MIN), ("chiller_electric_power", MECH_POWER_KW_MIN))
OFF_MAX = 0.05
FULL_MIN = 0.95
WINDOW = "3600s"          # trailing hour (t - 3600 s, t]
MAX_INTERVAL_SECONDS = 900.0  # a coarser trend interval makes the counts floors (internal constant, as the SQL)


def _proof(d: pd.DataFrame) -> tuple[pd.Series | None, str]:
    """The proof series: the first candidate that is ever on, else the first one bound; (None, '') when none is bound."""
    bound = []
    for role, thr in PROOF_CANDIDATES:
        if role not in d.columns:
            continue
        v = pd.to_numeric(d[role], errors="coerce").astype(float)
        if thr is not None:
            v = v.where(v.isna(), (v > thr).astype(float))
        if v.notna().any():
            bound.append((role, v))
    if not bound:
        return None, ""
    for role, v in bound:
        if (v > OFF_MAX).any():
            return v, role
    return bound[0][1], bound[0][0]


def _epoch(index: pd.DatetimeIndex) -> np.ndarray:
    """Epoch seconds of a (UTC or naive) datetime index."""
    zero = pd.Timestamp(0, tz="UTC") if index.tz is not None else pd.Timestamp(0)
    return np.asarray((index - zero) / pd.Timedelta(seconds=1), dtype=float)


def _held_all(index: pd.DatetimeIndex) -> np.ndarray:
    """Forward hold to the next row of the frame; the last row and a gap longer than one hour hold 0."""
    t = _epoch(index)
    dt = np.append(t[1:] - t[:-1], np.nan)
    return np.where((dt > 0.0) & (dt <= ELAPSED_MAX_GAP_SECONDS), dt, 0.0)


def short_cycle_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Raw fault mask on ``d.index``; ``d.attrs['short_cycle_assessment']`` says whether the equipment was assessed."""
    max_starts = float(p.get("max_starts_per_hour", 6.0))
    min_on = float(p.get("min_on_seconds", 600.0))
    min_short = float(p.get("min_short_cycles", 3.0))
    max_interval = MAX_INTERVAL_SECONDS
    gap = ELAPSED_MAX_GAP_SECONDS
    out = pd.Series(False, index=d.index)
    proof, src = _proof(d)
    d.attrs["short_cycle_proof"] = src
    if proof is None:
        d.attrs["short_cycle_assessment"] = "no_run_status"
        return out
    valid = proof.dropna()
    idx = valid.index
    t = _epoch(idx)
    v = valid.to_numpy(dtype=float)
    n = len(v)
    u = np.clip(v, 0.0, 1.0)
    cls = np.where(v <= OFF_MAX, 0, np.where(v >= FULL_MIN, 2, 1))
    dt_fwd = np.append(t[1:] - t[:-1], np.nan)
    dt_back = np.insert(t[1:] - t[:-1], 0, np.nan)
    brk = np.isnan(dt_back) | (dt_back > gap)
    in_gap = ~np.isnan(dt_fwd) & (dt_fwd <= gap)
    held = np.where(in_gap & (dt_fwd > 0.0), dt_fwd, 0.0)
    coarse = (~np.isnan(dt_fwd) & (dt_fwd > max_interval) & (dt_fwd <= gap)).astype(float)
    start_evt = np.zeros(n)
    short_evt = np.zeros(n)
    prev_closes = False
    k = 0
    chain_at_run_start = False
    c_start = c_seen_start = False
    on_s = 0.0
    for i in range(n):
        if cls[i] == 0:
            prev_closes = False
            continue
        run_start = bool(brk[i]) or cls[i - 1] == 0
        seen_rise = (not brk[i]) and i > 0 and cls[i - 1] == 0
        closes = False
        if cls[i] == 1:
            if brk[i] or cls[i - 1] != 1:      # a new chain of partial samples
                k = 0
                chain_at_run_start = run_start
            else:
                k += 1
            closes = (k % 2 == 1) if chain_at_run_start else (k % 2 == 0)
        if run_start or prev_closes:           # a cycle opens here
            c_seen_start = (not run_start) or seen_rise
            start_evt[i] = 1.0 if c_seen_start else 0.0
            on_s = 0.0
        on_s += u[i] * held[i]
        prev_closes = closes
        last = i + 1 >= n or cls[i + 1] == 0 or brk[i + 1] or closes
        if last:
            seen_stop = closes or (in_gap[i] and i + 1 < n and cls[i + 1] == 0)
            if c_seen_start and seen_stop and on_s < min_on:
                short_evt[i] = 1.0
    starts_h = pd.Series(start_evt, index=idx).rolling(WINDOW).sum().to_numpy()
    short_h = pd.Series(short_evt, index=idx).rolling(WINDOW).sum().to_numpy()
    coarse_h = pd.Series(coarse, index=idx).rolling(WINDOW).max().to_numpy() >= 0.5
    raw = (starts_h > max_starts) | (short_h >= min_short)
    raw_s = pd.Series(raw, index=idx)
    covered_row = pd.Series(~coarse_h | raw, index=idx).reindex(d.index).fillna(False).to_numpy(dtype=bool)
    floor_row = pd.Series(coarse_h & raw, index=idx).reindex(d.index).fillna(False).to_numpy(dtype=bool)
    held_all = _held_all(d.index)
    covered_s = float(held_all[covered_row].sum())
    if covered_s <= 0.0:
        d.attrs["short_cycle_assessment"] = "insufficient_trend"
    elif bool((floor_row & (held_all > 0.0)).any()):
        d.attrs["short_cycle_assessment"] = "coarse_floor"
    else:
        d.attrs["short_cycle_assessment"] = "assessed"
    d.attrs["short_cycle_covered_hours"] = covered_s / 3600.0
    return raw_s.reindex(d.index).fillna(False).astype(bool)
