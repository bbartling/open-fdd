"""Cross-sensor consistency checks (#1780): pandas twins of sql/fdd/postgres/rules/xs_mix.sql, xs_copy.sql, xs_clip.sql.

Sensor and mapping findings, not equipment faults. Each sets ``d.attrs["xs_assessment"]``; anything other than
``assessed`` is reported NOT_ASSESSED by the runner (never a silent pass). All values SI.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from open_fdd.rules.cookbook_catalog import FAN_ON_MIN, _f, norm_cmd

#: (role a, role b): the first role's movement over a matching run is the "changing" test
COPY_PAIRS = (
    ("return_air_temperature", "discharge_air_temperature"),
    ("mixed_air_temperature", "discharge_air_temperature"),
    ("mixed_air_temperature", "return_air_temperature"),
    ("zone_air_temperature", "discharge_air_temperature"),
    ("zone_air_temperature", "terminal_unit_discharge_air_temperature"),
)
#: (role, round-step parameter, default step, counted only while the fan is on)
CLIP_ROLES = (
    ("zone_air_co2", "co2_round", 100.0, False),
    ("discharge_air_static_pressure", "static_round", 25.0, True),
    ("discharge_air_volume_flow_rate", "flow_round", 50.0, True),
)
_EPS = 1e-6


def _col(d: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(d[name], errors="coerce") if name in d.columns else pd.Series(np.nan, index=d.index)


def _fan_on(d: pd.DataFrame, use_run_proof: bool) -> pd.Series:
    """fan status, else fan command, else (``use_run_proof``) the run proof, else on; per sample, as the SQL CASE."""
    status = _col(d, "supply_fan_operating_status")
    # A start/stop command is boolean 0/1. Keep that scale; percent roles are not this column.
    cmd = norm_cmd(d["supply_fan_command"], representation="fraction") if "supply_fan_command" in d.columns else pd.Series(np.nan, index=d.index)
    on = pd.Series(True, index=d.index)
    if use_run_proof:
        rp = _col(d, "operating_status")
        on = on.where(rp.isna(), rp > 0.05)
    on = on.where(cmd.isna(), cmd > FAN_ON_MIN)
    return on.where(status.isna(), status > 0.05).astype(bool)


def xs_mix(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """MAT outside [min(OAT, RAT) - mix_band, max(OAT, RAT) + mix_band] with the fan on (status, else command)."""
    del poll
    mat, oat, rat = _col(d, "mixed_air_temperature"), _col(d, "outdoor_air_intake_temperature"), _col(d, "return_air_temperature")
    ok = mat.notna() & oat.notna() & rat.notna()
    d.attrs["xs_assessment"] = "assessed" if ok.any() else "no_temperatures"
    band = _f(p, "mix_band", 1.111111)
    lo, hi = np.minimum(oat, rat), np.maximum(oat, rat)
    return (ok & _fan_on(d, False) & ((mat < lo - band) | (mat > hi + band))).fillna(False)


def xs_copy(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """A pair within copy_tol over a run of consecutive samples in which the first role moves by >= change_min."""
    del poll
    tol, change = _f(p, "copy_tol", 0.02), _f(p, "change_min", 1.0)
    raw = pd.Series(False, index=d.index)
    any_pair = False
    for a_role, b_role in COPY_PAIRS:
        a, b = _col(d, a_role), _col(d, b_role)
        both = a.notna() & b.notna()
        any_pair = any_pair or bool(both.any())
        match = both & ((a - b).abs() <= tol)
        run = (match != match.shift(fill_value=False)).cumsum()
        span = a.groupby(run).transform("max") - a.groupby(run).transform("min")
        raw = raw | (match & (span >= change))
    d.attrs["xs_assessment"] = "assessed" if any_pair else "no_pair"
    return raw.fillna(False)


def xs_clip(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Samples at the top value of a role clipped at a round full scale (see xs_clip.sql).

    clip_share is a percent (0-100, QUDT PERCENT), the same number SQL compares as CLIP_SHARE.
    """
    del poll
    share = _f(p, "clip_share", 5.0)
    on = _fan_on(d, True)
    raw = pd.Series(False, index=d.index)
    any_role = False
    for role, key, default, fan_dependent in CLIP_ROLES:
        v = _col(d, role)
        any_role = any_role or bool(v.notna().any())
        if fan_dependent:
            v = v.where(on)
        if not v.notna().any():
            continue
        top, low, step = float(v.max()), float(v.min()), _f(p, key, default)
        at = v.notna() & (v >= top - _EPS)
        if (top > 0 and low < top - _EPS and abs(top - step * round(top / step)) <= _EPS
                and 100.0 * int(at.sum()) >= share * int(v.notna().sum())):
            raw = raw | at
    d.attrs["xs_assessment"] = "assessed" if any_role else "no_clip_role"
    return raw.fillna(False)
