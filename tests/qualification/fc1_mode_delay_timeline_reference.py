"""Independent FC1 timeline math for mode-delay qualification (#1437, #1458).

Does not import ``open_fdd.rules.mode_delay``, ``cookbook_catalog._fc1_mode_stable``,
or SQL render helpers. Duplicates the product contract only as plain arithmetic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import pandas as pd

PRODUCT_MODE_DELAY_DEFAULT_MIN = 10.0
MAX_GAP_SECONDS = 3600.0


def _resolve_delay_min(params: Mapping[str, Any]) -> float:
    mode = (
        PRODUCT_MODE_DELAY_DEFAULT_MIN
        if "mode_delay_min" not in params
        else float(params["mode_delay_min"])
    )
    startup = float(params.get("startup_delay_min", 0.0))
    if not math.isfinite(mode) or mode < 0:
        raise ValueError(f"mode_delay_min invalid: {mode}")
    if not math.isfinite(startup) or startup < 0:
        raise ValueError(f"startup_delay_min invalid: {startup}")
    return max(mode, startup)


def _hold_rows(delay_min: float, poll_seconds: float) -> int:
    if poll_seconds < 1:
        raise ValueError("poll_seconds must be >= 1")
    return max(1, math.ceil(delay_min * 60.0 / poll_seconds))


def _fan_on_series(fan_status: Sequence[float], fan_on_min: float) -> list[bool]:
    return [float(v) > fan_on_min for v in fan_status]


def _mode_stable_mask(fan_on: Sequence[bool], rows: int) -> list[bool]:
    out: list[bool] = []
    for i in range(len(fan_on)):
        window = fan_on[max(0, i - rows + 1) : i + 1]
        out.append(all(window))
    return out


def _eligible_hold_seconds(index: pd.DatetimeIndex) -> list[float]:
    if len(index) == 0:
        return []
    held: list[float] = []
    for i, ts in enumerate(index):
        if i + 1 >= len(index):
            held.append(0.0)
            continue
        delta = (index[i + 1] - ts).total_seconds()
        if delta <= 0.0 or delta > MAX_GAP_SECONDS:
            held.append(0.0)
        else:
            held.append(float(delta))
    return held


def _confirm_mask(raw: Sequence[bool], index: pd.DatetimeIndex, confirm_seconds: float) -> list[bool]:
    if confirm_seconds <= 0:
        return list(raw)
    held = _eligible_hold_seconds(index)
    gap_after = [
        i + 1 < len(index)
        and (index[i + 1] - index[i]).total_seconds() > MAX_GAP_SECONDS
        for i in range(len(index))
    ]
    out = [False] * len(raw)
    streak_elapsed = 0.0
    prev_raw: bool | None = None
    for i, is_raw in enumerate(raw):
        if prev_raw is None or is_raw != prev_raw or (i > 0 and gap_after[i - 1]):
            streak_elapsed = 0.0
        prev_raw = is_raw
        if not is_raw:
            continue
        streak_elapsed += held[i]
        out[i] = streak_elapsed >= confirm_seconds
    return out


@dataclass(frozen=True)
class Fc1Timeline:
    eligible: list[bool]
    raw: list[bool]
    confirmed: list[bool]
    fault_seconds_by_day: dict[str, float]
    covered_seconds_by_day: dict[str, float]


def compute_fc1_timeline(
    *,
    index: pd.DatetimeIndex,
    fan_status: Sequence[float],
    duct_static: Sequence[float],
    duct_static_sp: Sequence[float],
    params: Mapping[str, Any],
    poll_seconds: float,
    confirm_seconds: float,
    require_operational_gate: bool = False,
) -> Fc1Timeline:
    n = len(index)
    eps_dsp = float(params.get("eps_dsp", 29.8608))
    eps_vfd = float(params.get("eps_vfd_spd", 0.13))
    fan_on_min = float(params.get("fan_on_min", 0.01))
    fan_hi = 1.0 - eps_vfd

    delay_min = _resolve_delay_min(params)
    rows = _hold_rows(delay_min, poll_seconds)
    fan_on = _fan_on_series(fan_status, fan_on_min)
    mode_stable = _mode_stable_mask(fan_on, rows)

    eligible = [True] * n
    if require_operational_gate:
        eligible = list(fan_on)

    raw: list[bool] = []
    for i in range(n):
        dsp = duct_static[i]
        sp = duct_static_sp[i]
        pressure_fault = (
            math.isfinite(dsp)
            and math.isfinite(sp)
            and dsp < sp - eps_dsp
            and fan_status[i] >= fan_hi
        )
        raw.append(
            bool(eligible[i])
            and fan_on[i]
            and mode_stable[i]
            and pressure_fault
        )

    confirmed = _confirm_mask(raw, index, confirm_seconds)
    held = _eligible_hold_seconds(index)

    fault_by_day: dict[str, float] = {}
    covered_by_day: dict[str, float] = {}
    utc = index.tz_convert("UTC")
    for i, ts in enumerate(utc):
        sec = held[i]
        if sec <= 0.0:
            continue
        day = ts.date().isoformat()
        covered_by_day[day] = covered_by_day.get(day, 0.0) + sec
        if confirmed[i]:
            fault_by_day[day] = fault_by_day.get(day, 0.0) + sec

    return Fc1Timeline(
        eligible=eligible,
        raw=raw,
        confirmed=confirmed,
        fault_seconds_by_day=fault_by_day,
        covered_seconds_by_day=covered_by_day,
    )


def build_mode_delay_grid_cases() -> list[dict[str, Any]]:
    """mode in {0,5,10,15,omitted} x poll {60,300,900} x startup {0, gt mode}."""
    cases: list[dict[str, Any]] = []
    modes: list[float | None] = [0.0, 5.0, 10.0, 15.0, None]
    polls = (60.0, 300.0, 900.0)
    for mode in modes:
        for poll in polls:
            gt = 15.0 if (mode is None or mode <= 10.0) else float(mode) + 5.0
            for startup in (0.0, gt):
                cases.append(
                    {
                        "mode_delay_min": mode,
                        "startup_delay_min": startup,
                        "poll_seconds": poll,
                    }
                )
    return cases


def build_synthetic_fc1_frame(
    *,
    poll_seconds: float,
    n_samples: int,
    start: str = "2026-04-01T08:00:00",
) -> pd.DataFrame:
    """Fan restart mid-series; persistent duct-static fault when fan is on."""
    idx = pd.date_range(start, periods=n_samples, freq=f"{int(poll_seconds)}s", tz="UTC")
    fan: list[float] = []
    for i in range(n_samples):
        fan.append(1.0 if i >= 2 else 0.0)
    return pd.DataFrame(
        {
            "duct-static-pressure": [0.20] * n_samples,
            "duct-static-pressure-sp": [1.50] * n_samples,
            "fan-status": fan,
            "fan-cmd": [1.0] * n_samples,
        },
        index=idx,
    )


def grid_params(case: Mapping[str, Any]) -> dict[str, float]:
    params: dict[str, float] = {
        "eps_vfd_spd": 0.13,
        "eps_dsp": 0.12,
        "fan_on_min": 0.01,
        "startup_delay_min": float(case["startup_delay_min"]),
        "require_operational_gate": 0.0,
        "confirm_min": 5.0,
    }
    mode = case.get("mode_delay_min")
    if mode is not None:
        params["mode_delay_min"] = float(mode)
    return params


def build_issue_1458_reproducer() -> tuple[pd.DataFrame, dict[str, float], float]:
    """300 s poll, fan-on across UTC day boundary, ``mode_delay_min`` omitted from params."""
    from scripts.ci import unit_contract_lib as uc
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl

    rules = {r["rule_id"]: r for r in cfl.load_rule_registry()}
    fc1 = rules["FC1"]
    params_ip, _ = cfl.resolve_rule_params_ip_si(fc1, uc.load_json(uc.METRIC_UNITS))
    params = {k: float(v) for k, v in params_ip.items() if k != "mode_delay_min"}

    spec = next(s for s in cfl.iter_dataset_specs() if s.equipment_id == "AHU_CASE_FC1")
    frame = cfl.prepare_ip_frame(
        spec.source["frame"],
        building_id=spec.building_id,
        equipment_id=spec.equipment_id,
        equipment_type=spec.equipment_type,
    )
    prev = frame.loc[frame.index.date.astype(str) == "2026-01-04"].iloc[-12:]
    day = frame.loc[frame.index.date.astype(str) == "2026-01-05"]
    d = pd.concat([prev, day])
    d.attrs.update(frame.attrs)
    return d, params, 300.0


def fc1_mode_stable_mutant_pre1437(
    d: pd.DataFrame, p: dict, poll: float
) -> pd.Series:
    """Frozen pre-#1437 ``_fc1_mode_stable`` (default 0, ignores startup, rolling max)."""
    import numpy as np
    from open_fdd.rules.cookbook_catalog import (
        FAN_ON_MIN,
        _fan,
        _gl36_value,
    )

    delay_min = float(p.get("mode_delay_min", 0.0))
    if delay_min <= 0 or d.empty:
        return pd.Series(True, index=d.index)
    fan_on_min = _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    fan = _fan(d)
    on = fan > fan_on_min
    samples = max(1, int(np.ceil(delay_min * 60.0 / max(float(poll), 1.0))))
    off_in_window = (~on).astype(int).rolling(samples, min_periods=1).max().astype(bool)
    return (on & ~off_in_window).fillna(False)
