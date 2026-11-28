"""Open-FDD Pandas cookbook — full rule catalog coded against the Haystack data model.

Every rule mirrors https://bbartling.github.io/open-fdd/rules/cookbook/pandas-cookbook.html
Rules are declarative: each carries the logical point roles it needs, plain-language
equation text, tunable slider params, and a pure compute function that
returns a RAW boolean fault mask. The cookbook_engine resolves roles against the data
model, builds a logical frame per equipment, runs applicable rules, and confirms faults.

All inputs and parameters are SI (°C, Δ°C, Pa, L/s, percent). The rules never convert or guess units;
convert at ingest and for display in the UI layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from open_fdd.rules.mode_delay import (
    PRODUCT_MODE_DELAY_MIN_DEFAULT,
    effective_mode_delay_min,
    fan_restart_stable,
    mode_delay_rows,
    resolve_mode_delay_params,
)
from open_fdd.rules.sensor_sweep_catalog import (
    ASSESSABLE_ROLES_BY_SWEEP,
    limits_for_haystack_role,
    quantity_for_haystack_role,
    stale_tolerance_for_role,
    starter_profile,
    sweep_assessable_role,
)

# ---------------------------------------------------------------------------
# Shared helpers (mirror cookbook "Setup & shared helpers")
# ---------------------------------------------------------------------------


def norm_cmd(
    s: pd.Series | None,
    *,
    representation: str = "percent",
) -> pd.Series:
    """Command or position as a fraction 0–1.

    Damper, valve and fan-speed roles arrive as PERCENT 0–100 (roles 1.1.0). The default divides by 100.
    A start/stop command is boolean 0/1: pass ``representation='fraction'`` so a stored 1 stays on.
    There is no magnitude guess.
    """
    from open_fdd.units.convert import norm_command

    if representation not in {"percent", "fraction"}:
        raise ValueError(
            f"norm_cmd representation must be percent|fraction, got {representation!r}"
        )
    return norm_command(s, representation=representation)  # type: ignore[arg-type]


def as_bool(s: pd.Series | None) -> pd.Series:
    if s is None:
        return pd.Series(dtype=bool)
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().any():
        return num.fillna(0) > 0.5
    return s.fillna(False).astype(bool)


def _sv_rate_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    from open_fdd.rules.sensor_rate import sv_rate_compute

    return sv_rate_compute(d, p, poll)


# Fractional command treated as "on" for always-on screening (same as fan_on elsewhere).
SCHED247_CMD_ON_FRAC = 0.05


def _pressure_on_mask(d: pd.DataFrame, p: dict) -> pd.Series | None:
    """True when a pressure sensor shows live operating pressure (equipment likely on)."""
    thr = _f(p, "pressure_on_min", 49.768)
    for role in ("discharge_air_static_pressure", "chilled_water_pressure_delta", "hw-diff-pressure"):
        if role not in d.columns or not d[role].notna().any():
            continue
        s = pd.to_numeric(d[role], errors="coerce")
        return (s.notna() & (s.abs() > thr)).reindex(d.index).fillna(False)
    return None


# #1670: one ranked proof list, the same in SQL (sched247_always_on.sql) and here. Statuses first
# (on when > 0.05, sql/fdd/run_proof.json), then boolean start/stop commands (on when > 0.5).
SCHED247_STATUS_ROLES = ("supply_fan_operating_status", "pump_operating_status", "chilled_water_pump_operating_status", "chiller_operating_status", "compressor_operating_status",
                         "chiller_electric_current")
SCHED247_COMMAND_ROLES = ("cooling_tower_fan_command", "supply_fan_command", "chilled_water_pump_command")
SCHED247_ON_THRESHOLD = 0.05
SCHED247_COMMAND_ON = 0.5
# #1670: an always-on verdict needs known proof for 90% of the observed window, and never less than one day.
SCHED247_MIN_COMPLETENESS = 0.9
SCHED247_MIN_WINDOW_SECONDS = 86400.0


def _sched247_ranked_proof(d: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Per sample: (on, known). The first non-null status wins over any command; neither is unknown (not OFF)."""
    on = pd.Series(np.nan, index=d.index, dtype=float)
    source = pd.Series("", index=d.index, dtype=object)
    for role in SCHED247_STATUS_ROLES:
        if role not in d.columns:
            continue
        vals = pd.to_numeric(d[role], errors="coerce")
        fill = on.isna() & vals.notna()
        on = on.where(~fill, (vals > SCHED247_ON_THRESHOLD).astype(float))
        source = source.where(~fill, role)
    for role in SCHED247_COMMAND_ROLES:
        if role not in d.columns:
            continue
        vals = norm_cmd(d[role], representation="fraction")
        fill = on.isna() & vals.notna()
        on = on.where(~fill, (vals > SCHED247_COMMAND_ON).astype(float))
        source = source.where(~fill, f"{role} (cmd)")
    return on, source


def _sched247(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Always-on runtime from ranked proof (#1670).

    Per sample the first non-null status wins over the command (run when > 0.05, the run-proof threshold); a
    sample with neither is UNKNOWN, never a proven OFF. Durations are elapsed holds (gap > 1 h and the last
    sample hold nothing). The verdict needs proven time >= 0.9 * max(observed window, 24 h); otherwise the rule
    is not assessed (``d.attrs['sched247_proof']['assessment']``). A qualifying equipment
    (proven_on / proven >= always_on_pct, time-weighted) faults on its proven-ON samples.
    Pressure is inferred evidence only — it does not OR into the FAULT mask (4.3 migration).
    """
    from open_fdd.rules.base import _eligible_hold_seconds, hours_true

    thr = _f(p, "always_on_pct", 95.0)
    on, source = _sched247_ranked_proof(d)
    known = on.notna()
    proven = (on == 1.0) & known
    held = _eligible_hold_seconds(d.index)
    if held is None:  # positional frame: poll-spaced samples
        held = pd.Series(float(poll), index=d.index)
        if len(held):
            held.iloc[-1] = 0.0
        window_s = float(poll) * max(len(d) - 1, 0)
    else:
        window_s = float((d.index.max() - d.index.min()).total_seconds()) if len(d) else 0.0
    on_s = float(held[proven].sum())
    off_s = float(held[known & ~proven].sum())
    if on_s + off_s <= 0.0:
        assessment = "no_proof"
    elif on_s + off_s < SCHED247_MIN_COMPLETENESS * max(window_s, SCHED247_MIN_WINDOW_SECONDS):
        assessment = "insufficient_proof"
    else:
        assessment = "assessed"

    inferred = _pressure_on_mask(d, p)
    inferred_h = hours_true(inferred.reindex(d.index).fillna(False).astype(bool), poll) if inferred is not None else 0.0
    status_known = source.ne("") & ~source.str.endswith("(cmd)")
    cmd_on = None
    for role in SCHED247_COMMAND_ROLES:
        if role in d.columns and d[role].notna().any():
            cmd_on = norm_cmd(d[role], representation="fraction") > SCHED247_COMMAND_ON
            break
    conflict = status_known & proven.ne(cmd_on) if cmd_on is not None else _false(d.index)
    used = sorted({s for s in source.unique() if s})
    d.attrs["sched247_proof"] = {
        "proof_source": ", ".join(used) if used else "none",
        "proof_confidence": 1.0 if status_known.any() else (0.5 if known.any() else 0.0),
        "proven_runtime_hours": round(on_s / 3600.0, 3),
        "inferred_runtime_hours": round(float(inferred_h), 3),
        "conflicting_signal_hours": round(hours_true(conflict, poll), 3),
        "window_hours": window_s / 3600.0,
        "proven_on_hours": on_s / 3600.0,
        "proven_off_hours": off_s / 3600.0,
        "unknown_hours": max(window_s - on_s - off_s, 0.0) / 3600.0,
        "assessment": assessment,
    }
    if assessment == "assessed" and 100.0 * on_s / (on_s + off_s) >= thr:
        return proven
    return _false(d.index)


def _f(p: dict, key: str, default: float) -> float:
    try:
        v = p.get(key, default)
        return float(v) if v is not None else float(default)
    except (TypeError, ValueError):
        return float(default)


def _param_si_abs_temp_to_series(_d: pd.DataFrame, _role: str, value_c: float) -> float:
    """Rule frames store canonical SI; parameters already use degC."""
    return float(value_c)


def _param_si_delta_temp_to_series(_d: pd.DataFrame, _role: str, delta_c: float) -> float:
    """Rule frames store canonical SI; difference parameters use degC_delta."""
    return float(delta_c)


def _param_si_flow_to_series(_d: pd.DataFrame, value_lps: float) -> float:
    """Rule frames store canonical SI; flow parameters already use L/s."""
    return float(value_lps)


def _false(index) -> pd.Series:
    return pd.Series(False, index=index)


def flatline_mask(series: pd.Series, tol: float, window: int) -> pd.Series:
    window = max(2, int(window))
    roll_min = series.rolling(window, min_periods=window).min()
    roll_max = series.rolling(window, min_periods=window).max()
    return series.notna() & ((roll_max - roll_min) <= tol)


# ---------------------------------------------------------------------------
# Per-sensor validation limits (SI: °C, %, Pa; see sensor_sweep_catalog)
# ---------------------------------------------------------------------------

SWEEP_ROLE_CATALOG: tuple[str, ...] = ASSESSABLE_ROLES_BY_SWEEP["SV-RANGE"]

SENSOR_LIMITS: dict[str, dict[str, float]] = {
    role: lim
    for role in SWEEP_ROLE_CATALOG
    if (lim := limits_for_haystack_role(role)) is not None
}

# Sensor roles the validation sweep will check on any equipment (if present)
SWEEP_SENSOR_ROLES = list(ASSESSABLE_ROLES_BY_SWEEP["SV-RANGE"])

# Flatline/stale detection targets analog temperature & humidity sensors only.
# Pressure points (e.g. duct static) legitimately rest at ~0 when equipment is off,
# so they would false-positive as "stuck" — exclude them from stuck-sensor sweeps.
FLATLINE_SENSOR_ROLES = list(ASSESSABLE_ROLES_BY_SWEEP["SV-FLATLINE"])
# Stale is missing data, so it follows the SV-STALE allowlist (pressure and zone airflow included).
STALE_SENSOR_ROLES = list(ASSESSABLE_ROLES_BY_SWEEP["SV-STALE"])

SPIKE_SENSOR_ROLES = list(ASSESSABLE_ROLES_BY_SWEEP["SV-SPIKE"])


def sensor_type_for_role(role: str) -> str:
    """HVAC quantity bucket for UI grouping (Temperature / Humidity / Pressure / Flow)."""
    r = role.lower()
    if "humid" in r:
        return "Humidity"
    if "pressure" in r or "static" in r or r.endswith("-dp"):
        return "Pressure"
    if "flow" in r:
        return "Flow"
    if "temp" in r or "wetbulb" in r or "dewpoint" in r:
        return "Temperature"
    return "Other"


def _role_type_scale(p: dict, role: str, *, kind: str) -> float:
    """Per-type scale for range/spike limits (multiplies global scale when present)."""
    stype = sensor_type_for_role(role).lower()
    key = f"{kind}_scale_{stype}"
    # Accept both humidity and humid key aliases
    if key not in p and stype == "humidity":
        key = f"{kind}_scale_humidity"
    try:
        return float(p.get(key, 1.0) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def _evidence_row(
    role: str,
    mask: pd.Series,
    *,
    poll: float,
    series: pd.Series | None = None,
    silence_hours: float = 0.0,
) -> dict:
    from open_fdd.rules.base import hours_true

    m = mask.fillna(False).astype(bool)
    n_fault = int(m.sum())
    hours = round(hours_true(m, poll), 3) if n_fault else 0.0
    first_ts = last_ts = None
    if n_fault and isinstance(m.index, pd.DatetimeIndex):
        idx = m.index[m]
        first_ts = str(idx[0])
        last_ts = str(idx[-1])
    row: dict = {
        "role": role,
        "sensor_type": sensor_type_for_role(role),
        "fault_samples": n_fault,
        "fault_hours": hours,
        "silence_hours": float(silence_hours),
        "first_fault_timestamp": first_ts,
        "last_fault_timestamp": last_ts,
        "faulted": n_fault > 0,
    }
    if series is not None and n_fault:
        num = pd.to_numeric(series, errors="coerce")
        vals = num[m]
        if vals.notna().any():
            row["fault_mean"] = round(float(vals.mean()), 3)
            row["fault_min"] = round(float(vals.min()), 3)
            row["fault_max"] = round(float(vals.max()), 3)
    return row


def _stash_sweep_evidence(
    d: pd.DataFrame,
    per_role: dict[str, pd.Series],
    *,
    poll: float,
    rule_tag: str,
    segments: dict[str, list[dict]] | None = None,
) -> None:
    """Store per-role evidence + masks on the frame for the runner/UI."""
    evidence = []
    masks: dict[str, pd.Series] = {}
    for role, mask in per_role.items():
        s = pd.to_numeric(d[role], errors="coerce") if role in d.columns else None
        evidence.append(_evidence_row(role, mask, poll=poll, series=s))
        masks[role] = mask.fillna(False).astype(bool)
    d.attrs["sv_sweep_evidence"] = evidence
    d.attrs["sv_sweep_masks"] = masks
    d.attrs["sv_sweep_rule"] = rule_tag
    d.attrs["sv_sweep_segments"] = segments or {}


def _observed_end_seconds(d: pd.DataFrame) -> float | None:
    if isinstance(d.index, pd.DatetimeIndex) and len(d.index):
        return float(_index_epoch_seconds(pd.DatetimeIndex([d.index.max()]))[0])
    return None


def _index_epoch_seconds(index: pd.DatetimeIndex) -> np.ndarray:
    """Convert any pandas datetime resolution to epoch seconds consistently."""
    try:
        normalized = index.as_unit("ns")
    except AttributeError:  # pandas < 2.0 compatibility
        normalized = index.astype("datetime64[ns]")
    return normalized.asi8.astype("float64") / 1e9


def _valid_series_times(series: pd.Series, poll: float) -> tuple[pd.Series, np.ndarray]:
    """Return non-null values with elapsed timestamps, retaining missing-row gaps."""
    values = pd.to_numeric(series, errors="coerce")
    if isinstance(values.index, pd.DatetimeIndex):
        valid = values.dropna().sort_index(kind="mergesort")
        return valid, _index_epoch_seconds(valid.index)
    present = values.notna().to_numpy()
    positions = np.flatnonzero(present)
    valid = values.iloc[positions]
    return valid, positions.astype("float64") * max(float(poll), 1.0)


def _elapsed_segments(
    d: pd.DataFrame,
    series: pd.Series,
    raw_fault: pd.Series,
    *,
    poll: float,
    max_silence_hours: float,
) -> list[dict]:
    """Build sample-and-hold intervals, split into normal and silent time."""
    valid, epochs = _valid_series_times(series, poll)
    if not len(valid):
        return []
    raw = raw_fault.reindex(valid.index).fillna(False).astype(bool)
    observed_end = _observed_end_seconds(d)
    if isinstance(valid.index, pd.DatetimeIndex):
        end_epoch = observed_end if observed_end is not None else float(epochs[-1])
    else:
        end_epoch = max(0, len(d.index) - 1) * max(float(poll), 1.0)
    cap = max(0.0, float(max_silence_hours)) * 3600.0
    out = []
    for i, timestamp in enumerate(valid.index):
        next_epoch = float(epochs[i + 1]) if i + 1 < len(epochs) else end_epoch
        dt = max(0.0, next_epoch - float(epochs[i]))
        normal = min(dt, cap)
        silent = max(0.0, dt - cap)
        out.append({
            "timestamp": timestamp,
            "raw_fault": bool(raw.iloc[i]),
            "normal_seconds": normal,
            "silence_seconds": silent,
            "break_before": bool(i > 0 and float(epochs[i]) - float(epochs[i - 1]) > cap),
        })
    return out


def _window_flatline_mask(
    series: pd.Series,
    *,
    hours: float,
    tolerance: float,
    max_silence_hours: float,
    poll: float = 300.0,
    gate: pd.Series | None = None,
) -> pd.Series:
    """Detect stable values over elapsed sample-hold windows without crossing gaps."""
    s = pd.to_numeric(series, errors="coerce")
    result = _false(s.index)
    valid, times = _valid_series_times(s, poll)
    if not len(valid):
        return result
    values = valid.to_numpy(dtype="float64")
    cutoff_width = max(0.0, float(hours)) * 3600.0
    max_silence = max(0.0, float(max_silence_hours)) * 3600.0
    gate_values = gate.reindex(valid.index).fillna(False).to_numpy(dtype=bool) if gate is not None else None
    segment_start = 0
    left = 0
    flags = np.zeros(len(valid), dtype=bool)
    for i, current in enumerate(times):
        if i and current - times[i - 1] > max_silence:
            segment_start = i
            left = i
        cutoff = current - cutoff_width
        while left < i and times[left] < cutoff:
            left += 1
        # A window is eligible only when the current continuous data segment
        # reaches all the way back to the cutoff.
        if times[segment_start] > cutoff:
            continue
        lo = left
        window_values = values[lo:i + 1]
        first_epoch = times[lo]
        # Include the prior sample when its held interval crosses the cutoff;
        # this is the elapsed-time equivalent of RANGE ... PRECEDING.
        if lo > segment_start and first_epoch > cutoff and times[lo - 1] <= cutoff:
            window_values = np.concatenate(([values[lo - 1]], window_values))
        span = float(np.max(window_values) - np.min(window_values))
        if span <= tolerance and (gate_values is None or bool(gate_values[i])):
            flags[i] = True
    result.loc[valid.index] = flags
    return result


def _flatline_energized(d: pd.DataFrame) -> pd.Series:
    """Mirror SQL's row-wise first-non-null energized proof selection."""
    idx = d.index
    tests = (
        ("supply_fan_operating_status", 0.05),
        ("supply_fan_command", 0.01),
        ("discharge_air_volume_flow_rate", 23.597350),
        ("pump_operating_status", 0.05),
        ("chilled_water_pump_command", 0.05),
        ("chiller_operating_status", 0.05),
    )
    energized = pd.Series(True, index=idx, dtype=bool)
    unresolved = pd.Series(True, index=idx, dtype=bool)
    for role, threshold in tests:
        if role not in d.columns or not unresolved.any():
            continue
        values = pd.to_numeric(d[role], errors="coerce")
        present = unresolved & values.notna()
        energized.loc[present] = values.loc[present].gt(threshold)
        unresolved.loc[present] = False
    return energized


def _sweep_energized(d: pd.DataFrame, p: dict) -> pd.Series:
    """Run-proof gate of the SV sweeps (#1608): one resolved ``run-proof`` signal, the same one the SQL sweeps read."""
    from open_fdd.run_proof import sweep_gate_mask

    return sweep_gate_mask(d, p)


def _sweep_segments(d: pd.DataFrame, masks: dict[str, pd.Series], poll: float, p: dict) -> dict[str, list[dict]]:
    max_silence = _f(p, "max_silence_hours", 0.5)
    return {
        role: _elapsed_segments(d, pd.to_numeric(d[role], errors="coerce"), mask,
                                poll=poll, max_silence_hours=max_silence)
        for role, mask in masks.items() if role in d.columns
    }


def _publish_elapsed_sweep(d: pd.DataFrame, masks: dict[str, pd.Series], *, poll: float, p: dict, rule_tag: str) -> pd.Series:
    segments = _sweep_segments(d, masks, poll, p)
    # #1673: the part of a gap beyond max_silence_hours is unknown for value sweeps (not covered, not a fault);
    # missing data is SV-STALE's alone.
    for rows in segments.values():
        for row in rows:
            row["silence_seconds"] = 0.0
    return _publish_segments(d, segments, poll=poll, rule_tag=rule_tag)


def _publish_segments(d: pd.DataFrame, segments: dict[str, list[dict]], *, poll: float, rule_tag: str) -> pd.Series:
    event_masks = {role: _false(d.index) for role in segments}
    for role, rows in segments.items():
        for row in rows:
            if (row["raw_fault"] and row["normal_seconds"] > 0) or row["silence_seconds"] > 0:
                event_masks[role].loc[row["timestamp"]] = True
    _stash_sweep_evidence(d, event_masks, poll=poll, rule_tag=rule_tag, segments=segments)
    combined = _false(d.index)
    for event_mask in event_masks.values():
        combined |= event_mask
    return combined


def confirm_sensor_sweep_segments(
    d: pd.DataFrame,
    *,
    confirm_seconds: float,
) -> dict:
    """Confirm raw sweep intervals and return per-role elapsed fault evidence."""
    segments = d.attrs.get("sv_sweep_segments") or {}
    index = d.index
    raw_union = _false(index)
    confirmed_union = _false(index)
    evidence = []
    confirmed_roles: dict[str, pd.Series] = {}
    role_hours = []
    for role, rows in segments.items():
        raw_mask = _false(index)
        confirmed_mask = _false(index)
        streak_seconds = 0.0
        previous_raw = False
        fault_hours = silence_hours = 0.0
        confirmed_count = 0
        first_ts = last_ts = None
        for row in rows:
            raw = bool(row["raw_fault"])
            normal = float(row["normal_seconds"])
            silent = float(row["silence_seconds"])
            timestamp = row["timestamp"]
            if (raw and not previous_raw) or not raw or row.get("break_before", False):
                streak_seconds = 0.0
            if raw:
                streak_seconds += normal
            normal_confirmed = raw and (float(confirm_seconds) <= 0 or streak_seconds >= float(confirm_seconds))
            if normal_confirmed:
                fault_hours += normal / 3600.0
            silence_hours += silent / 3600.0
            has_fault_interval = (raw and normal > 0) or silent > 0
            has_confirmed_interval = (normal_confirmed and normal > 0) or silent > 0
            if has_fault_interval:
                raw_mask.loc[timestamp] = True
            if has_confirmed_interval:
                confirmed_mask.loc[timestamp] = True
                confirmed_count += 1
                if first_ts is None:
                    first_ts = str(timestamp)
                last_ts = str(timestamp)
            previous_raw = raw
        combined_hours = fault_hours + silence_hours
        role_hours.append(combined_hours)
        raw_union |= raw_mask
        confirmed_union |= confirmed_mask
        confirmed_roles[role] = confirmed_mask.astype(int)
        series = pd.to_numeric(d[role], errors="coerce") if role in d.columns else None
        ev = _evidence_row(role, confirmed_mask, poll=0, series=series, silence_hours=silence_hours)
        ev.update({
            "fault_hours": combined_hours,
            "faulted": combined_hours > 0.0,
            "fault_samples": confirmed_count,
            "first_fault_timestamp": first_ts,
            "last_fault_timestamp": last_ts,
        })
        if (sid := _series_id(d, role)) is not None:   # #1763: the point keeps its identity in the evidence
            ev["series_id"] = sid
        evidence.append(ev)
    return {
        "raw_mask": raw_union,
        "confirmed_mask": confirmed_union,
        "evidence": evidence,
        "confirmed_roles": confirmed_roles,
        "fault_hours": max(role_hours, default=0.0),
    }

# Analog 0–100% (or 0–1) control outputs swept by PID-HUNT-1.
# Map by *role* (valve / damper / speed cmd) — never by a BAS point named "Loop".
CONTROL_OUTPUT_ROLES = [
    "outdoor_air_intake_damper_position_command",
    "cooling_valve_position_command",
    "heating_valve_position_command",
    "damper_position",
    "terminal_unit_heating_valve_position_command",
    "supply_fan_command",
    "return_fan_command",
    "chilled_water_pump_command",
    "hw-pump-cmd",
    "condenser_water_pump_command",
    "pump-cmd",
    "control-output-pct",
]

# Column-name tokens that are *not* hunting AOs (loads, RH, setpoints, etc.).
_CONTROL_OUTPUT_COL_EXCLUDE = (
    "terminalload",
    "terminal_load",
    "humidity",
    "relative_humidity",
    "setpoint",
    "minimum_position",
    "min_pos",
    "minpos",
    "wind_speed",
    "alarm",
)


# ---------------------------------------------------------------------------
# Rule model
# ---------------------------------------------------------------------------


@dataclass
class CookbookParam:
    key: str
    label: str
    unit: str
    min: float
    max: float
    step: float
    default: float
    # Slider direction hint for UI: "fewer" (↑ → fewer faults), "stricter" (↑ → more faults), "" = neutral.
    direction: str = ""

    def __post_init__(self) -> None:
        # Fraction thresholds are PERCENT 0-100 on the wire. The runner divides them back to 0-1
        # before compute, except ratio keys the rule compares in percent.
        if self.unit in ("frac", "pct", "%"):
            self.min = float(self.min) * 100.0
            self.max = float(self.max) * 100.0
            self.step = float(self.step) * 100.0
            self.default = float(self.default) * 100.0
            self.unit = "PERCENT"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "unit": self.unit,
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "default": self.default,
            "direction": self.direction,
        }

    def help_text(self) -> str:
        base = self.label
        if self.direction == "fewer":
            return f"{base} — increasing this usually flags fewer faults."
        if self.direction == "stricter":
            return f"{base} — increasing this usually flags more faults (stricter / wider detection)."
        return base


@dataclass
class CookbookRule:
    id: str
    title: str
    family: str  # sensor | ahu | vav | plant | heatpump | weather | trim
    equipment_kinds: list[str]
    required_roles: list[str]
    equation: str
    compute: Callable[[pd.DataFrame, dict, float], pd.Series]
    params: list[CookbookParam] = field(default_factory=list)
    optional_roles: list[str] = field(default_factory=list)
    confirm_seconds: float = 300.0
    sensor_sweep: bool = False
    control_output_sweep: bool = False
    # One-sentence fault description for UI / DOCX / RULE_PLOT_CATALOG (not the equation).
    summary: str = ""

    def defaults(self) -> dict[str, float]:
        return {p.key: p.default for p in self.params}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "family": self.family,
            "equipment_kinds": self.equipment_kinds,
            "required_roles": self.required_roles,
            "optional_roles": self.optional_roles,
            "equation": self.equation,
            "summary": self.summary,
            "confirm_seconds": self.confirm_seconds,
            "sensor_sweep": self.sensor_sweep,
            "control_output_sweep": self.control_output_sweep,
            "params": [p.to_dict() for p in self.params],
        }


CONFIRM_PARAM = lambda default_min=5.0, mx=60.0: CookbookParam(  # noqa: E731
    "confirm_min",
    "Fault confirm delay",
    "min",
    0.0,
    mx,
    1.0,
    default_min,
    direction="fewer",
)

MODE_DELAY_PARAM = lambda: CookbookParam(  # noqa: E731
    "mode_delay_min", "Mode-change suspension (product default)", "min", 0.0, 60.0, 1.0,
    PRODUCT_MODE_DELAY_MIN_DEFAULT, direction="fewer"
)
FAN_ON_PARAM = lambda: CookbookParam(  # noqa: E731
    "fan_on_min", "Fan-on command threshold", "frac", 0.0, 0.25, 0.01, FAN_ON_MIN
)
EPS_TEMP_PARAM = lambda key, label, default=0.638889: CookbookParam(  # noqa: E731
    key, label, "Δ°C", 0.0, 5.555556, 0.138889, default, direction="fewer"
)
DELTA_TSF_PARAM = lambda: CookbookParam(  # noqa: E731
    "delta_supply_fan", "Supply-fan heat rise ΔTSF", "Δ°C", 0.0, 2.777778, 0.027778, DELTA_SUPPLY_FAN
)
ECON_MIN_PARAM = lambda: CookbookParam(  # noqa: E731
    "econ_min_pos", "Economizer minimum-position threshold", "frac", 0.0, 0.5, 0.01, AHU_MIN_OA_DPR
)
ECON_FULL_PARAM = lambda: CookbookParam(  # noqa: E731
    "econ_full_open", "Economizer full-open threshold", "frac", 0.5, 1.0, 0.01, 0.90
)
CLG_ON_PARAM = lambda: CookbookParam(  # noqa: E731
    "clg_on_min", "Cooling-command ON threshold", "frac", 0.0, 0.25, 0.01, 0.01
)
CLG_INACTIVE_PARAM = lambda: CookbookParam(  # noqa: E731
    "clg_inactive_max", "Cooling-command inactive ceiling", "frac", 0.0, 0.5, 0.01, 0.10, direction="fewer"
)
LEGACY_MIX_PARAM = lambda: CookbookParam(  # noqa: E731
    "mix_tol", "Legacy master sensor tolerance (sets all ε values)", "Δ°C", 0.0, 5.555556, 0.138889, MIX_TOL, direction="fewer"
)
LEGACY_SUPPLY_PARAM = lambda: CookbookParam(  # noqa: E731
    "supply_tol", "Legacy SAT tolerance master (sets εSAT)", "Δ°C", 0.0, 5.555556, 0.138889, SUPPLY_TOL, direction="fewer"
)


# ---------------------------------------------------------------------------
# Sensor validation sweep (SV-1/2/3 range, SV-5 stale, SV-6 flatline, SV-7 spike)
# Applied only to the canonical assessable roles present in the equipment data.
# ---------------------------------------------------------------------------


def _sweep_limits(d: pd.DataFrame) -> dict | None:
    """Role limits override for this frame (``d.attrs['sweep_limits']``, a load_role_limits() result), else the shipped set."""
    raw = d.attrs.get("sweep_limits")
    return raw if isinstance(raw, dict) else None


def _series_id(d: pd.DataFrame, role: str) -> str | None:
    """#1763: the point (series id) behind a role column (``d.attrs['series_ids']``), for its own saved limits."""
    raw = d.attrs.get("series_ids")
    sid = raw.get(role) if isinstance(raw, dict) else None
    return str(sid) if sid else None


def _sweep_profile(d: pd.DataFrame, role: str, limits: dict | None, rule_tag: str, **tuners) -> dict:
    """The sensor's SI limits (sensor, then role, then rule tuner, then quantity starter; see starter_profile)."""
    prof = starter_profile(role, series_id=_series_id(d, role), limits=limits, **tuners)
    if not prof["assessed"]:
        raise ValueError(f"{rule_tag} role {role!r} has no SI limit ({prof['reason']})")
    return prof


def _units_map(d: pd.DataFrame) -> dict[str, str]:
    raw = d.attrs.get("units_map")
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v}
    return {}


def _sweep_range(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    per_role: dict[str, pd.Series] = {}
    units_map = _units_map(d)
    # SQL's range query gates each ordinary sample on the point-priority
    # energized signal. Long-silence tails are added later and remain ungated.
    energized = _sweep_energized(d, p)
    limits = _sweep_limits(d)
    for role in SWEEP_SENSOR_ROLES:
        if role not in d.columns:
            continue
        if not sweep_assessable_role(role, None, units_map, rule_id="SV-RANGE", limits=limits):
            continue
        s = pd.to_numeric(d[role], errors="coerce")
        if not s.notna().any():
            continue
        prof = _sweep_profile(d, role, limits, "SV-RANGE")
        base_lo, base_hi = prof["lo"], prof["hi"]
        type_scale = _role_type_scale(p, role, kind="range")
        # Widen limits when scale > 1 (more forgiving); shrink when scale < 1.
        mid = (base_lo + base_hi) / 2.0
        half = (base_hi - base_lo) / 2.0 * max(type_scale, 1e-6)
        lo, hi = mid - half, mid + half
        # BACnet sensor failures commonly arrive as IEEE +/-Inf. Treat any
        # present non-finite number as a hard range fault before JSON/Parquet
        # quality handling converts it to a NaN marker.
        role_mask = s.notna() & (~np.isfinite(s) | (s < lo) | (s > hi)) & energized.reindex(s.index).fillna(False)
        per_role[role] = role_mask
    return _publish_elapsed_sweep(d, per_role, poll=poll, p=p, rule_tag="SV-RANGE")


def _sweep_flatline(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    tol = _f(p, "flatline_tol", 0.055556)
    hours = _f(p, "flatline_hours", 1.0)
    max_silence = _f(p, "max_silence_hours", 0.5)
    # SV-FLATLINE SQL always requires an energized proof for ordinary samples;
    # preserve the legacy pandas-only knob in the catalog, but do not let it
    # diverge from SQL. Silence intervals are still accounted independently.
    gate = _sweep_energized(d, p)
    per_role: dict[str, pd.Series] = {}
    units_map = _units_map(d)
    limits = _sweep_limits(d)
    for role in FLATLINE_SENSOR_ROLES:
        if role not in d.columns:
            continue
        if not sweep_assessable_role(role, None, units_map, rule_id="SV-FLATLINE", limits=limits):
            continue
        s = pd.to_numeric(d[role], errors="coerce")
        if not s.notna().any():
            continue
        flat_tol = _sweep_profile(d, role, limits, "SV-FLATLINE", flatline_tol=tol)["flat_tol"]
        if flat_tol is None:
            raise ValueError(f"SV-FLATLINE role {role!r} has no declared tolerance")
        role_gate = gate
        if role_gate is not None:
            role_gate = role_gate.reindex(s.index).fillna(False)
        role_mask = _window_flatline_mask(
            s,
            hours=hours,
            tolerance=flat_tol,
            max_silence_hours=max_silence,
            poll=poll,
            gate=role_gate,
        )
        per_role[role] = role_mask
    return _publish_elapsed_sweep(d, per_role, poll=poll, p=p, rule_tag="SV-FLATLINE")


def _sweep_spike(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    max_silence = _f(p, "max_silence_hours", 0.5)
    max_silence_seconds = max_silence * 3600.0
    per_role: dict[str, pd.Series] = {}
    units_map = _units_map(d)
    require_gate = _f(p, "require_run_proof", _f(p, "require_operational_gate", 1.0)) >= 0.5
    energized = _sweep_energized(d, p)
    coverage_pct = 100.0 * float(energized.mean()) if len(energized) else 0.0
    gate_ok = (not require_gate) or coverage_pct >= _f(p, "minimum_active_coverage_pct", 5.0)
    limits = _sweep_limits(d)
    for role in SPIKE_SENSOR_ROLES:
        if role not in d.columns:
            continue
        if not sweep_assessable_role(role, None, units_map, rule_id="SV-SPIKE", limits=limits):
            continue
        s = pd.to_numeric(d[role], errors="coerce")
        if not s.notna().any():
            continue
        type_scale = _role_type_scale(p, role, kind="spike")
        spike = _sweep_profile(d, role, limits, "SV-SPIKE")["spike_delta"]
        if spike is None:
            raise ValueError(f"SV-SPIKE role {role!r} has no SI limit")
        limit = spike * type_scale
        valid = s.dropna().sort_index(kind="mergesort")
        role_mask = _false(s.index)
        if len(valid) > 1:
            jumps = valid.diff().abs()
            if isinstance(valid.index, pd.DatetimeIndex):
                gaps = valid.index.to_series().diff().dt.total_seconds()
                jumps = jumps.where(gaps <= max_silence_seconds, np.nan)
            else:
                jumps = jumps.where(float(poll) <= max_silence_seconds, np.nan)
            jumped = jumps.gt(limit).fillna(False)
            if require_gate:
                jumped &= energized.reindex(valid.index).fillna(False)
                if not gate_ok:
                    jumped[:] = False
            role_mask.loc[valid.index] = jumped.to_numpy()
        per_role[role] = role_mask
    return _publish_elapsed_sweep(d, per_role, poll=poll, p=p, rule_tag="SV-SPIKE")


def _sweep_stale(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Missing data (#1673): a sensor is stale while it has no valid sample for longer than ``stale_after_hours``.

    No value test (a stuck value that is still polled is SV-FLATLINE) and no run-proof gate. Every assessable sensor
    column of the frame is an expected series, so a column with no valid sample is assessed over the whole window.
    The window is the frame's first timestamp to its observed end; the window start, every valid sample and the end
    split it into intervals, and an interval longer than the threshold contributes (interval - threshold) of fault
    time. A saved legacy ``max_silence_hours`` is the same threshold. Twin of ``sql/fdd/postgres/rules/sv_stale.sql``.
    """
    threshold = max(0.0, _f(p, "stale_after_hours", _f(p, "max_silence_hours", 0.5))) * 3600.0
    units_map = _units_map(d)
    limits = _sweep_limits(d)
    segments: dict[str, list[dict]] = {}
    if not len(d.index):
        return _false(d.index)
    if isinstance(d.index, pd.DatetimeIndex):
        start = float(_index_epoch_seconds(pd.DatetimeIndex([d.index.min()]))[0])
        end = float(_observed_end_seconds(d))
    else:
        start, end = 0.0, max(0, len(d.index) - 1) * max(float(poll), 1.0)
    anchor = d.index.min() if isinstance(d.index, pd.DatetimeIndex) else d.index[0]
    for role in STALE_SENSOR_ROLES:
        if role not in d.columns or not sweep_assessable_role(role, None, units_map, rule_id="SV-STALE", limits=limits):
            continue
        valid, epochs = _valid_series_times(pd.to_numeric(d[role], errors="coerce"), poll)
        points = [(start, anchor)] + [(float(e), ts) for ts, e in zip(valid.index, epochs) if start <= float(e) <= end]
        points.append((end, None))
        rows = []
        for (t0, label), (t1, _) in zip(points, points[1:]):
            dt = t1 - t0
            if dt <= 0:
                continue
            rows.append({"timestamp": label, "raw_fault": False, "normal_seconds": min(dt, threshold),
                         "silence_seconds": max(0.0, dt - threshold), "break_before": False})
        segments[role] = rows
    return _publish_segments(d, segments, poll=poll, rule_tag="SV-STALE")


def _pid_hunt_1(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Suspected control-output hunting across any present 0–100% analog roles."""
    from open_fdd.rules.pid_hunting import PidHuntingParams, hunting_fault_mask, iter_control_output_series

    params = PidHuntingParams(
        change_deadband_pct=_f(p, "change_deadband_pct", 1.0),
        minimum_span_pct=_f(p, "minimum_span_pct", 20.0),
        total_variation_fault_pct=_f(p, "total_variation_fault_pct", 500.0),
        minimum_equivalent_cycles=_f(p, "minimum_equivalent_cycles", 2.5),
        minimum_reversals=int(_f(p, "minimum_reversals", 4)),
        minimum_coverage_pct=_f(p, "minimum_coverage_pct", 80.0),
    )
    mask = _false(d.index)
    enable_col = "operating_mode_status" if "operating_mode_status" in d.columns else None
    for _label, series in iter_control_output_series(d):
        enabled = d[enable_col] if enable_col else None
        fault, _ = hunting_fault_mask(
            series,
            params=params,
            poll_seconds=poll,
            enabled=enabled,
        )
        mask = mask | fault.reindex(d.index).fillna(False)
    return mask


# ---------------------------------------------------------------------------
# Air handling unit rules (FC1–FC15 + additional patterns)
# ---------------------------------------------------------------------------

MIX_TOL = 0.6388888889
SUPPLY_TOL = 0.6388888889
AHU_MIN_OA_DPR = 0.05
DELTA_SUPPLY_FAN = 0.3055555556
FAN_ON_MIN = 0.01


def _gl36_value(p: dict, key: str, legacy_key: str | None, default: float) -> float:
    """Read a canonical GL36 variable, retaining old session-param compatibility."""
    if key in p:
        return float(p[key])
    if legacy_key and legacy_key in p:
        return float(p[legacy_key])
    return float(default)


def _gl36_mode_stable(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """False during the product mode-delay holdoff after a fan restart (#1459).

    Matches product SQL (render_rule.py) via ``open_fdd.rules.mode_delay``.
    """
    delay_min = effective_mode_delay_min(resolve_mode_delay_params(p))
    fan_on = _fan(d) > _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    return fan_restart_stable(fan_on, mode_delay_rows(delay_min, float(poll)))


def _gl36_fault(raw: pd.Series, d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    return raw.fillna(False) & _gl36_mode_stable(d, p, poll)


def _fc1_mode_stable(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Fan restart holdoff — same contract as GL36 rules and postgres FC1 (#1437, #1459)."""
    return _gl36_mode_stable(d, p, poll)


def _fan(d: pd.DataFrame) -> pd.Series:
    # Match production SQL (supply_fan_operating_status then supply_fan_command) — Wave J / #875.
    if "supply_fan_operating_status" in d.columns:
        return as_bool(d["supply_fan_operating_status"]).astype(float)
    if "supply_fan_command" in d.columns:
        return norm_cmd(d["supply_fan_command"], representation="fraction").fillna(0)
    return pd.Series(1.0, index=d.index)


def fc1(d, p, poll):
    default_err = 29.8608
    if "eps_dsp" in p:
        err = float(p["eps_dsp"])
    elif "duct_static_err" in p:
        err = float(p["duct_static_err"])
    else:
        err = default_err
    speed_err = _gl36_value(p, "eps_vfd_spd", None, 0.13)
    fan_hi = _gl36_value(p, "fan_hi", None, 1.0 - speed_err)
    if "supply_fan_speed_command" not in d.columns:
        return _false(d.index)
    speed = norm_cmd(d["supply_fan_speed_command"])
    fan = _fan(d)
    raw = (
        d["discharge_air_static_pressure"].notna() & d["discharge_air_static_pressure_setpoint"].notna()
        & (d["discharge_air_static_pressure"] < d["discharge_air_static_pressure_setpoint"] - err)
        & (fan > FAN_ON_MIN)
        & (speed >= fan_hi)
    )
    return raw.fillna(False) & _fc1_mode_stable(d, p, poll)


def fc2(d, p, poll):
    """MAT below OAT/RAT mixing envelope (GL36 B).

    ``mix_tol`` widens the envelope on both sides:
    ``mixed_air_temperature + tol < min(return_air_temperature - tol, oat - tol)`` ≡ ``mixed_air_temperature < min(return_air_temperature, oat) - 2·tol``.
    Never subtract the same tol from both sides of the inequality (that cancels).
    """
    eps_mat = _gl36_value(p, "eps_mat", "mix_tol", MIX_TOL)
    eps_rat = _gl36_value(p, "eps_rat", "mix_tol", MIX_TOL)
    eps_oat = _gl36_value(p, "eps_oat", "mix_tol", MIX_TOL)
    fan_on = _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    fan = _fan(d)
    raw = (
        (fan > fan_on)
        & d["mixed_air_temperature"].notna() & d["outdoor_air_intake_temperature"].notna() & d["return_air_temperature"].notna()
        & ((d["mixed_air_temperature"] + eps_mat) < np.minimum(d["return_air_temperature"] - eps_rat, d["outdoor_air_intake_temperature"] - eps_oat))
    )
    return _gl36_fault(raw, d, p, poll)


def fc3(d, p, poll):
    eps_mat = _gl36_value(p, "eps_mat", "mix_tol", MIX_TOL)
    eps_rat = _gl36_value(p, "eps_rat", "mix_tol", MIX_TOL)
    eps_oat = _gl36_value(p, "eps_oat", "mix_tol", MIX_TOL)
    fan_on = _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    fan = _fan(d)
    raw = (
        (fan > fan_on)
        & d["mixed_air_temperature"].notna() & d["outdoor_air_intake_temperature"].notna() & d["return_air_temperature"].notna()
        & ((d["mixed_air_temperature"] - eps_mat) > np.maximum(d["return_air_temperature"] + eps_rat, d["outdoor_air_intake_temperature"] + eps_oat))
    )
    return _gl36_fault(raw, d, p, poll)


def fc4(d, p, poll):
    """PID hunting — operating-state entry transitions per hour."""
    delta_os_max = _f(p, "delta_os_max", 5.0)
    htg = norm_cmd(d["heating_valve_position_command"]).fillna(0) if "heating_valve_position_command" in d else pd.Series(0.0, index=d.index)
    clg = norm_cmd(d["cooling_valve_position_command"]).fillna(0) if "cooling_valve_position_command" in d else pd.Series(0.0, index=d.index)
    fan = _fan(d)
    econ = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0) if "outdoor_air_intake_damper_position_command" in d else pd.Series(0.0, index=d.index)
    modes = pd.DataFrame(index=d.index)
    modes["heating"] = ((htg > 0) & (clg == 0) & (fan > 0) & (econ <= AHU_MIN_OA_DPR)).astype(int)
    modes["econ_only"] = ((htg == 0) & (clg == 0) & (fan > 0) & (econ > AHU_MIN_OA_DPR)).astype(int)
    modes["econ_mech"] = ((htg == 0) & (clg > 0) & (fan > 0) & (econ > AHU_MIN_OA_DPR)).astype(int)
    modes["mech_only"] = ((htg == 0) & (clg > 0) & (fan > 0) & (econ <= AHU_MIN_OA_DPR)).astype(int)
    # Loader moves timestamp into the DatetimeIndex — prefer index over a column.
    if isinstance(d.index, pd.DatetimeIndex):
        ts = pd.DatetimeIndex(d.index)
    elif "timestamp" in d.columns:
        from open_fdd.timestamps import to_utc_datetime

        ts = pd.DatetimeIndex(to_utc_datetime(d["timestamp"], errors="coerce"))
    else:
        return _false(d.index)
    proven = pd.Series(True, index=d.index)
    if float(p.get("require_run_proof", 1.0)) >= 0.5:
        # #1631: entries are counted over proven samples only (twin of fc4_os_hunting.sql): the sequence skips unproven
        # time, so a transition across it is not an entry. No proof bound at all is SKIPPED by the runner before this.
        from open_fdd.run_proof import derive_run_proof, proof_on

        proof, _src = derive_run_proof(d)
        if proof is not None:
            proven = proof_on(proof).reindex(d.index).fillna(False).astype(bool)
    sub = modes[proven.values]
    entries = (sub.eq(1) & sub.shift().ne(1)).reindex(modes.index, fill_value=False)
    entries.index = ts
    hourly = entries.resample("1h").sum()
    flagged_hours = hourly[(hourly > delta_os_max).any(axis=1)].index
    floor = ts.floor("1h")
    return pd.Series(floor.isin(flagged_hours), index=d.index)


def fc5(d, p, poll):
    """SAT cold when heating commanded (GL36 D). ``mix_tol`` applies to both SAT and MAT."""
    eps_sat = _gl36_value(p, "eps_sat", "mix_tol", MIX_TOL)
    eps_mat = _gl36_value(p, "eps_mat", "mix_tol", MIX_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    fan_on = _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    htg_on = _f(p, "htg_on_min", 0.01)
    fan = _fan(d)
    htg = norm_cmd(d["heating_valve_position_command"]).fillna(0)
    raw = (
        d["discharge_air_temperature"].notna() & d["mixed_air_temperature"].notna()
        & (fan > fan_on) & (htg > htg_on)
        & ((d["discharge_air_temperature"] + eps_sat) <= (d["mixed_air_temperature"] - eps_mat + delta_tsf))
    )
    return _gl36_fault(raw, d, p, poll)


def fc6(d, p, poll):
    airflow_err = _gl36_value(p, "eps_airflow", "airflow_err", 15.0)
    oat_rat_min = _gl36_value(p, "delta_t_min", "oat_rat_delta_min", 2.777778)
    design_flow = _f(p, "min_flow_design", 2359.735)
    fan_on = _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    fan = _fan(d)
    rat_minus_oat = (d["return_air_temperature"] - d["outdoor_air_intake_temperature"]).abs()
    pct_oa = ((d["mixed_air_temperature"] - d["return_air_temperature"]) / (d["outdoor_air_intake_temperature"] - d["return_air_temperature"]).replace(0, np.nan)).clip(lower=0)
    perc_oamin = design_flow / d["terminal_unit_discharge_air_total_volume_flow_rate"].replace(0, np.nan)
    oa_err = (pct_oa - perc_oamin).abs() * 100.0
    raw = (
        d["mixed_air_temperature"].notna() & d["outdoor_air_intake_temperature"].notna() & d["return_air_temperature"].notna() & d["terminal_unit_discharge_air_total_volume_flow_rate"].notna()
        & (rat_minus_oat >= oat_rat_min) & (oa_err > airflow_err) & (fan > fan_on)
    )
    return _gl36_fault(raw, d, p, poll)


def fc7(d, p, poll):
    sat_err = _gl36_value(p, "eps_sat", "sat_err", 0.638889)
    fan_on = _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    htg_full = _f(p, "htg_full_min", 0.9)
    fan = _fan(d)
    htg = norm_cmd(d["heating_valve_position_command"]).fillna(0)
    raw = (
        d["discharge_air_temperature"].notna() & d["discharge_air_temperature_setpoint"].notna()
        & (fan > fan_on) & (d["discharge_air_temperature"] < d["discharge_air_temperature_setpoint"] - sat_err) & (htg >= htg_full)
    )
    return _gl36_fault(raw, d, p, poll)


def fc8(d, p, poll):
    eps_mat = _gl36_value(p, "eps_mat", "mix_tol", MIX_TOL)
    eps_sat = _gl36_value(p, "eps_sat", "supply_tol", SUPPLY_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    econ_min = _f(p, "econ_min_pos", AHU_MIN_OA_DPR)
    clg_inactive = _f(p, "clg_inactive_max", 0.1)
    econ = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0)
    clg = norm_cmd(d["cooling_valve_position_command"]).fillna(0)
    sat_mat_err = (d["discharge_air_temperature"] - delta_tsf - d["mixed_air_temperature"]).abs()
    sqrt_tol = float(np.sqrt(eps_sat**2 + eps_mat**2))
    raw = (
        d["discharge_air_temperature"].notna() & d["mixed_air_temperature"].notna()
        & (econ > econ_min) & (clg < clg_inactive) & (sat_mat_err > sqrt_tol)
    )
    return _gl36_fault(raw, d, p, poll)


def fc9(d, p, poll):
    eps_oat = _gl36_value(p, "eps_oat", "mix_tol", MIX_TOL)
    eps_sat = _gl36_value(p, "eps_sat", "mix_tol", MIX_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    econ_min = _f(p, "econ_min_pos", AHU_MIN_OA_DPR)
    clg_inactive = _f(p, "clg_inactive_max", 0.1)
    econ = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0)
    clg = norm_cmd(d["cooling_valve_position_command"]).fillna(0)
    raw = (
        d["outdoor_air_intake_temperature"].notna() & d["discharge_air_temperature_setpoint"].notna()
        & (econ > econ_min) & (clg < clg_inactive)
        & ((d["outdoor_air_intake_temperature"] - eps_oat) > (d["discharge_air_temperature_setpoint"] - delta_tsf + eps_sat))
    )
    return _gl36_fault(raw, d, p, poll)


def fc10(d, p, poll):
    eps_mat = _gl36_value(p, "eps_mat", "mix_tol", MIX_TOL)
    eps_oat = _gl36_value(p, "eps_oat", "mix_tol", MIX_TOL)
    econ_full = _f(p, "econ_full_open", 0.9)
    clg_on = _f(p, "clg_on_min", 0.01)
    econ = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0)
    clg = norm_cmd(d["cooling_valve_position_command"]).fillna(0)
    abs_mat_oat = (d["mixed_air_temperature"] - d["outdoor_air_intake_temperature"]).abs()
    sqrt_tol = float(np.sqrt(eps_mat**2 + eps_oat**2))
    raw = d["mixed_air_temperature"].notna() & d["outdoor_air_intake_temperature"].notna() & (clg > clg_on) & (econ > econ_full) & (abs_mat_oat > sqrt_tol)
    return _gl36_fault(raw, d, p, poll)


def fc11(d, p, poll):
    eps_oat = _gl36_value(p, "eps_oat", "mix_tol", MIX_TOL)
    eps_sat = _gl36_value(p, "eps_sat", "mix_tol", MIX_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    econ_full = _f(p, "econ_full_open", 0.9)
    clg_on = _f(p, "clg_on_min", 0.01)
    econ = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0)
    clg = norm_cmd(d["cooling_valve_position_command"]).fillna(0)
    raw = (
        d["outdoor_air_intake_temperature"].notna() & d["discharge_air_temperature_setpoint"].notna() & (clg > clg_on) & (econ > econ_full)
        & ((d["outdoor_air_intake_temperature"] + eps_oat) < (d["discharge_air_temperature_setpoint"] - delta_tsf - eps_sat))
    )
    return _gl36_fault(raw, d, p, poll)


def fc12(d, p, poll):
    eps_mat = _gl36_value(p, "eps_mat", "mix_tol", MIX_TOL)
    eps_sat = _gl36_value(p, "eps_sat", "supply_tol", SUPPLY_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    econ_min = _f(p, "econ_min_pos", AHU_MIN_OA_DPR)
    econ_full = _f(p, "econ_full_open", 0.9)
    clg_on = _f(p, "clg_on_min", 0.01)
    econ = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0)
    clg = norm_cmd(d["cooling_valve_position_command"]).fillna(0)
    sat_check = d["discharge_air_temperature"] - eps_sat - delta_tsf
    mat_check = d["mixed_air_temperature"] + eps_mat
    raw = (
        d["discharge_air_temperature"].notna() & d["mixed_air_temperature"].notna() & (clg > clg_on)
        & (sat_check > mat_check) & ((econ <= econ_min) | (econ > econ_full))
    )
    return _gl36_fault(raw, d, p, poll)


def fc13(d, p, poll):
    sat_err = _gl36_value(p, "eps_sat", "sat_err", 0.638889)
    econ_min = _f(p, "econ_min_pos", AHU_MIN_OA_DPR)
    econ_full = _f(p, "econ_full_open", 0.9)
    clg_full = _f(p, "clg_full_min", 0.9)
    econ = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0)
    clg = norm_cmd(d["cooling_valve_position_command"]).fillna(0)
    raw = (
        d["discharge_air_temperature"].notna() & d["discharge_air_temperature_setpoint"].notna() & (clg >= clg_full)
        & (d["discharge_air_temperature"] > d["discharge_air_temperature_setpoint"] + sat_err) & ((econ <= econ_min) | (econ > econ_full))
    )
    return _gl36_fault(raw, d, p, poll)


def fc14(d, p, poll):
    eps_ccet = _gl36_value(p, "eps_ccet", "mix_tol", MIX_TOL)
    eps_cclt = _gl36_value(p, "eps_cclt", "mix_tol", MIX_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    econ_min = _f(p, "econ_min_pos", AHU_MIN_OA_DPR)
    clg_inactive = _f(p, "clg_inactive_max", 0.1)
    htg_on = _f(p, "htg_on_min", 0.01)
    econ = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0)
    clg = norm_cmd(d["cooling_valve_position_command"]).fillna(0)
    htg = norm_cmd(d["heating_valve_position_command"]).fillna(0) if "heating_valve_position_command" in d else pd.Series(0.0, index=d.index)
    fan = _fan(d)
    delta = d["cooling_coil_inlet_air_temperature"] - d["cooling_coil_outlet_air_temperature"]
    tol = float(np.sqrt(eps_ccet**2 + eps_cclt**2)) + delta_tsf
    raw = (
        d["cooling_coil_inlet_air_temperature"].notna() & d["cooling_coil_outlet_air_temperature"].notna()
        & (delta >= tol)
        & (((econ > econ_min) & (clg < clg_inactive)) | ((htg > htg_on) & (fan > 0)))
    )
    return _gl36_fault(raw, d, p, poll)


def fc15(d, p, poll):
    eps_hcet = _gl36_value(p, "eps_hcet", "mix_tol", MIX_TOL)
    eps_hclt = _gl36_value(p, "eps_hclt", "mix_tol", MIX_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    econ_min = _f(p, "econ_min_pos", AHU_MIN_OA_DPR)
    econ_full = _f(p, "econ_full_open", 0.9)
    clg_inactive = _f(p, "clg_inactive_max", 0.1)
    clg_on = _f(p, "clg_on_min", 0.01)
    econ = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0)
    clg = norm_cmd(d["cooling_valve_position_command"]).fillna(0)
    delta = d["heating_coil_inlet_air_temperature"] - d["heating_coil_outlet_air_temperature"]
    tol = float(np.sqrt(eps_hcet**2 + eps_hclt**2)) + delta_tsf
    raw = (
        d["heating_coil_inlet_air_temperature"].notna() & d["heating_coil_outlet_air_temperature"].notna()
        & (delta >= tol)
        & (((econ > econ_min) & (clg < clg_inactive)) | ((clg > clg_on) & (econ <= econ_min)) | ((clg > clg_on) & (econ > econ_full)))
    )
    return _gl36_fault(raw, d, p, poll)


def ahu_sat_dev(d, p, poll):
    err = _f(p, "sat_dev_err", 2.777778)
    return d["discharge_air_temperature"].notna() & d["discharge_air_temperature_setpoint"].notna() & (d["discharge_air_temperature"].sub(d["discharge_air_temperature_setpoint"]).abs() > err)


def ahu_duct_high(d, p, poll):
    """Duct static above SP + margin. Gate (not equation) decides fan-vs-pressure active window."""
    default_margin = 62.21
    margin = _f(p, "duct_high_margin", default_margin)
    return (
        d["discharge_air_static_pressure"].notna()
        & d["discharge_air_static_pressure_setpoint"].notna()
        & (d["discharge_air_static_pressure"] > d["discharge_air_static_pressure_setpoint"] + margin)
    )


def ahu_simul_heat_cool(d, p, poll):
    thr = _f(p, "valve_open_pct", 0.10)
    htg = norm_cmd(d["heating_valve_position_command"]).fillna(0)
    clg = norm_cmd(d["cooling_valve_position_command"]).fillna(0)
    return (htg > thr) & (clg > thr)


# ---------------------------------------------------------------------------
# Economizer & ventilation (ECON-1..5) — ECON-3 handled specially in engine
# ---------------------------------------------------------------------------


def econ1(d, p, poll):
    oat_min = _f(p, "econ1_oat_min", 12.777778)
    fan = _fan(d)
    econ = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0)
    return (fan > FAN_ON_MIN) & d["outdoor_air_intake_damper_position_command"].notna() & d["outdoor_air_intake_temperature"].notna() & (econ < 0.05) & (d["outdoor_air_intake_temperature"] > oat_min)


def econ2(d, p, poll):
    oat_hi = _f(p, "econ2_oat_hi", 17.222222)
    dmpr = _f(p, "econ2_damper", 0.42)
    econ = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0)
    return d["outdoor_air_intake_temperature"].notna() & d["outdoor_air_intake_damper_position_command"].notna() & (d["outdoor_air_intake_temperature"] > oat_hi) & (econ > dmpr)


def econ4(d, p, poll):
    oa_min_pct = _f(p, "oa_min_pct", 21.0)
    rat_oat_min = _f(p, "oat_rat_delta_min", 1.2222222222222223)
    fan = _fan(d)
    oa_frac = (d["mixed_air_temperature"] - d["return_air_temperature"]) / (d["outdoor_air_intake_temperature"] - d["return_air_temperature"]).replace(0, np.nan) * 100.0
    return (
        (fan > FAN_ON_MIN) & d["mixed_air_temperature"].notna() & d["return_air_temperature"].notna() & d["outdoor_air_intake_temperature"].notna()
        & ((d["return_air_temperature"] - d["outdoor_air_intake_temperature"]).abs() > rat_oat_min) & (oa_frac < oa_min_pct)
    )


def econ5(d, p, poll):
    over = _f(p, "preheat_over", 1.222222)
    return (
        d["preheat_heating_coil_outlet_air_temperature"].notna() & d["discharge_air_temperature_setpoint"].notna() & d["outdoor_air_intake_temperature"].notna() & d["heating_valve_position_command"].notna()
        & (norm_cmd(d["heating_valve_position_command"]).fillna(0) > 0.01)
        & (
            ((d["outdoor_air_intake_temperature"] > d["discharge_air_temperature_setpoint"]) & (d["preheat_heating_coil_outlet_air_temperature"] - d["outdoor_air_intake_temperature"] > over))
            | ((d["outdoor_air_intake_temperature"] < d["discharge_air_temperature_setpoint"]) & (d["preheat_heating_coil_outlet_air_temperature"] - d["discharge_air_temperature_setpoint"] > over))
        )
    )


# ---------------------------------------------------------------------------
# VAV zones
# ---------------------------------------------------------------------------


def _vav_air_on(d: pd.DataFrame, flow_min: float) -> pd.Series:
    """Fan/air-flow-running proxy for a VAV box.

    VAV terminals have no fan of their own; the box only sees conditioned air when the
    parent AHU supply fan runs. We use measured box airflow as that proxy: air moving
    means the fan is on. When no airflow point is modeled we can't gate, so return True.
    """
    if "discharge_air_volume_flow_rate" in d.columns:
        thr = _param_si_flow_to_series(d, flow_min)
        return pd.to_numeric(d["discharge_air_volume_flow_rate"], errors="coerce").fillna(0) > thr
    return pd.Series(True, index=d.index)


def _unoccupied_mask(d: pd.DataFrame) -> pd.Series:
    col = next((c for c in ("occupancy_status", "occ_mode", "occ-mode") if c in d.columns), None)
    if col is None:
        return _false(d.index)
    occ_raw = d[col]
    occ_str = occ_raw.astype(str).str.strip().str.lower()
    label_unocc = occ_str.isin(
        {"unoccupied", "unocc", "off", "false", "night", "standby", "setback", "no"}
    )
    occ_num = pd.to_numeric(occ_raw, errors="coerce")
    numeric_unocc = occ_num.notna() & (occ_num <= 0.05)
    return label_unocc | numeric_unocc


def vav1_occupied_mask(d: pd.DataFrame, p: dict | None = None) -> tuple[pd.Series, str]:
    """Samples where the comfort band may be scored.

    ``require_occupied`` defaults on. A mapped occupancy column or an Overview
    weekly calendar (``occupancy_schedule``) keeps unoccupied hours off this
    rule so night setback stays on VAV-2. With neither signal, the rule is not
    assessed (``ungated_no_occ``).
    """
    params = p or {}
    if _f(params, "require_occupied", 1.0) < 0.5:
        return pd.Series(True, index=d.index), "require_occupied_off"
    if any(c in d.columns and d[c].notna().any() for c in ("occupancy_status", "occ_mode", "occ-mode")):
        return (~_unoccupied_mask(d)).fillna(False), "occupancy_status"
    sched = params.get("occupancy_schedule") if isinstance(params, dict) else None
    if isinstance(sched, dict) and isinstance(d.index, pd.DatetimeIndex):
        from open_fdd.analytics.occupancy import OccupancySchedule, occupied_mask

        mask = occupied_mask(d.index, OccupancySchedule.from_dict(sched))
        return mask.reindex(d.index).fillna(False), "occupancy_schedule"
    return pd.Series(False, index=d.index), "ungated_no_occ"


def _zone_comfort_band(p: dict | None, role_units: dict | None = None) -> tuple[float, float]:
    _ = role_units
    lo = _f(p, "zone_lo", 21.111111)
    hi = _f(p, "zone_hi", 23.888889)
    return lo, hi


def vav1(d, p, poll):
    """Comfort band during occupied hours when a schedule or occ column is set."""
    lo = _param_si_abs_temp_to_series(d, "zone_air_temperature", _f(p, "zone_lo", 21.111111))
    hi = _param_si_abs_temp_to_series(d, "zone_air_temperature", _f(p, "zone_hi", 23.888889))
    zt = pd.to_numeric(d["zone_air_temperature"], errors="coerce")
    occupied, _src = vav1_occupied_mask(d, p)
    return zt.notna() & ((zt < lo) | (zt > hi)) & occupied


def vav2(d, p, poll):
    """Unoccupied zone stays warmer than heating setback (night setback miss)."""
    hi = _param_si_abs_temp_to_series(d, "zone_air_temperature", _f(p, "setback_hi", 20.0))
    zt = pd.to_numeric(d["zone_air_temperature"], errors="coerce")
    return zt.notna() & _unoccupied_mask(d) & (zt > hi)


def vav3(d, p, poll):
    oat_hi = _param_si_abs_temp_to_series(d, "outdoor_air_intake_temperature", _f(p, "reheat_oat", 25.555556))
    reheat_thr = _f(p, "reheat_pct", 0.52)
    flow_min = _f(p, "flow_on_min", 11.798689)
    reheat = norm_cmd(d["terminal_unit_heating_valve_position_command"]).fillna(0)
    return _vav_air_on(d, flow_min) & d["outdoor_air_intake_temperature"].notna() & (d["outdoor_air_intake_temperature"] > oat_hi) & (reheat > reheat_thr)


def vav4(d, p, poll):
    full_open = _f(p, "full_open_pct", 0.975)
    hours = _f(p, "sustain_hours", 1.5)
    flow_min = _f(p, "flow_on_min", 11.798689)
    roll = max(2, int(round(hours * 3600 / max(poll, 1))))
    dmp = norm_cmd(d["damper_position"]).fillna(0)
    return (
        _vav_air_on(d, flow_min) & dmp.notna() & (dmp > full_open)
        & (dmp.rolling(roll, min_periods=roll).min() > full_open)
    )


def vav5(d, p, poll):
    dmp = norm_cmd(d["damper_position"]).fillna(0)
    flow_thr = _param_si_flow_to_series(d, 23.597372)
    return d["discharge_air_volume_flow_rate"].notna() & (d["discharge_air_volume_flow_rate"] > flow_thr) & (dmp < 0.10)


def vav6(d, p, poll):
    """Reheat open while OA is cool enough for free cooling."""
    oat_hi = _param_si_abs_temp_to_series(d, "outdoor_air_intake_temperature", _f(p, "free_cool_oat", 18.333333))
    reheat_thr = _f(p, "reheat_pct", 0.25)
    reheat = norm_cmd(d["terminal_unit_heating_valve_position_command"]).fillna(0)
    oat = pd.to_numeric(d["outdoor_air_intake_temperature"], errors="coerce")
    clg = pd.Series(True, index=d.index)
    if "cooling_operating_mode_status" in d.columns and d["cooling_operating_mode_status"].notna().any():
        clg = as_bool(d["cooling_operating_mode_status"])
    return oat.notna() & clg.fillna(False) & (oat < oat_hi) & (reheat > reheat_thr)


def vav7(d, p, poll):
    """Min-flow violation OR fixed/high airflow while air is moving (mins too high / no modulate)."""
    under = (
        d["discharge_air_volume_flow_rate"].notna() & d["discharge_air_volume_flow_rate_minimum"].notna() & (d["discharge_air_volume_flow_rate"] < d["discharge_air_volume_flow_rate_minimum"])
        if "discharge_air_volume_flow_rate_minimum" in d.columns
        else _false(d.index)
    )
    flow = pd.to_numeric(d["discharge_air_volume_flow_rate"], errors="coerce") if "discharge_air_volume_flow_rate" in d.columns else None
    if flow is None:
        return under
    flow_min = _f(p, "flow_on_min", 11.798689)
    air_on = _vav_air_on(d, flow_min)
    window = max(6, int(round(3600.0 / max(float(poll), 1.0))))
    roll_std = flow.rolling(window, min_periods=max(3, window // 2)).std()
    roll_mean = flow.rolling(window, min_periods=max(3, window // 2)).mean()
    max_std = _param_si_flow_to_series(d, _f(p, "fixed_flow_max_std", 7.079211))
    min_mean = _param_si_flow_to_series(d, _f(p, "fixed_flow_min_mean", 94.389489))
    fixed_high = air_on & flow.notna() & (roll_std < max_std) & (roll_mean > min_mean)
    high_min = _false(d.index)
    if "discharge_air_volume_flow_rate_minimum" in d.columns:
        high_min_thr = _param_si_flow_to_series(d, _f(p, "high_min_flow_sp", 117.986861))
        high_min = (
            air_on
            & d["discharge_air_volume_flow_rate_minimum"].notna()
            & (pd.to_numeric(d["discharge_air_volume_flow_rate_minimum"], errors="coerce") > high_min_thr)
            & (roll_std < max_std)
        )
    return under.fillna(False) | fixed_high.fillna(False) | high_min.fillna(False)


def vav_reheat_stuck(d, p, poll):
    """Reheat valve commanded open but the box's discharge air never warms above inlet.

    Inlet temp = duct air arriving from the AHU (≈ AHU discharge). Discharge temp = air
    leaving the box after the reheat coil. Reheat open + air flowing + no rise → stuck /
    failed reheat valve or coil. Fully computed from VAV-local sensors.
    """
    cmd_thr = _f(p, "reheat_cmd", 0.30)
    min_rise = _param_si_delta_temp_to_series(
        d, "terminal_unit_discharge_air_temperature", _f(p, "min_rise", 1.666667)
    )
    flow_min = _f(p, "flow_on_min", 11.798689)
    reheat = norm_cmd(d["terminal_unit_heating_valve_position_command"]).fillna(0)
    rise = d["terminal_unit_discharge_air_temperature"] - d["terminal_unit_inlet_air_temperature"]
    return (
        _vav_air_on(d, flow_min)
        & d["terminal_unit_discharge_air_temperature"].notna() & d["terminal_unit_inlet_air_temperature"].notna()
        & (reheat > cmd_thr) & (rise < min_rise)
    )


def vav_vs_ahu_leave(d, p, poll):
    """VAV leave temp far from parent AHU SAT (fedBy) — broken reheat or sensor/rogue box.

    Requires topology enrich: ``air_handling_unit_discharge_air_temperature`` copied from parent AHU onto the VAV frame.
    Without ``air_handling_unit_discharge_air_temperature``, the rule is SKIPPED_MISSING_ROLES by the engine.
    """
    band = _param_si_delta_temp_to_series(d, "terminal_unit_discharge_air_temperature", _f(p, "delta", 4.444444))
    flow_min = _f(p, "flow_on_min", 11.798689)
    leave = pd.to_numeric(d["terminal_unit_discharge_air_temperature"], errors="coerce")
    ahu = pd.to_numeric(d["air_handling_unit_discharge_air_temperature"], errors="coerce")
    return (
        _vav_air_on(d, flow_min)
        & leave.notna()
        & ahu.notna()
        & ((leave - ahu).abs() > band)
    )


# ---------------------------------------------------------------------------
# Fan-coil / standalone zone controllers
# ---------------------------------------------------------------------------


def _fcu_fan_on(d: pd.DataFrame) -> pd.Series:
    """Use status wherever present, with command fallback per sample."""
    if "supply_fan_operating_status" in d.columns:
        status = as_bool(d["supply_fan_operating_status"])
        if "supply_fan_command" in d.columns:
            command = norm_cmd(d["supply_fan_command"], representation="fraction").fillna(0) > 0.10
            return status.where(d["supply_fan_operating_status"].notna(), command)
        return status
    if "supply_fan_command" in d.columns:
        return norm_cmd(d["supply_fan_command"], representation="fraction").fillna(0) > 0.10
    return _false(d.index)


def fcu_sensor_null(d, p, poll):
    if "zone_air_temperature" not in d.columns:
        return pd.Series(False, index=d.index)
    zone = pd.to_numeric(d["zone_air_temperature"], errors="coerce")
    sp = pd.to_numeric(d["zone_air_temperature_setpoint"], errors="coerce")
    eligible = sp.notna()
    null_fraction = 100.0 * float(zone[eligible].isna().mean()) if eligible.any() else 0.0
    return eligible & zone.isna() & (null_fraction >= _f(p, "null_fraction", 90.0))


def fcu_htg_coil(d, p, poll):
    heat = norm_cmd(d["heating_valve_position_command"])
    rise = pd.to_numeric(d["discharge_air_temperature"], errors="coerce") - pd.to_numeric(
        d["zone_air_temperature"], errors="coerce"
    )
    coil_delta = _param_si_delta_temp_to_series(
        d, "discharge_air_temperature", _f(p, "coil_delta", 3.0)
    )
    return _fcu_fan_on(d) & heat.notna() & (heat >= _f(p, "valve_open", 0.80)) & (rise < coil_delta)


def coil_perf(d, p, poll):
    """Generic coil performance (#1641), twin of sql/fdd/postgres/rules/coil_perf.sql.

    Per sample: heating mode when the heating valve (heating-valve, else reheat-valve) >= valve_open and the cooling
    valve, if bound, <= valve_shut; cooling mode when the cooling valve >= valve_open and the heating / reheat valves, if
    bound, <= valve_shut. The temperature pair is the first complete one of: coil entering/leaving sensors, mixed ->
    discharge air, VAV inlet -> discharge, zone -> discharge. Fault: heating with (leave - enter) < min_dt, or cooling
    with (enter - leave) < min_dt, fan on (status, else command), and airflow above flow_on_min where it is bound.
    No coil valve or no temperature pair with data -> ``d.attrs["coil_perf_assessment"]`` says why (the runner reports
    NOT_ASSESSED, never a silent pass)."""
    def col(name):
        return pd.to_numeric(d[name], errors="coerce") if name in d.columns else pd.Series(np.nan, index=d.index)

    def cmd(name):
        return norm_cmd(d[name]) if name in d.columns else pd.Series(np.nan, index=d.index)

    valve_open, valve_shut = _f(p, "valve_open", 0.8), _f(p, "valve_shut", 0.05)
    min_dt = _f(p, "min_dt", 3.0)
    htg_v, rh_v, clg = cmd("heating_valve_position_command"), cmd("terminal_unit_heating_valve_position_command"), cmd("cooling_valve_position_command")
    htg = htg_v.where(htg_v.notna(), rh_v)

    def ladder(pairs):
        out = pd.Series(np.nan, index=d.index)
        for leave, enter, sign in pairs:
            diff = sign * (col(leave) - col(enter))
            out = out.where(out.notna(), diff)
        return out

    rise = ladder([("heating_coil_outlet_air_temperature", "heating_coil_inlet_air_temperature", 1), ("discharge_air_temperature", "mixed_air_temperature", 1),
                   ("terminal_unit_discharge_air_temperature", "terminal_unit_inlet_air_temperature", 1), ("discharge_air_temperature", "zone_air_temperature", 1)])
    drop = ladder([("cooling_coil_outlet_air_temperature", "cooling_coil_inlet_air_temperature", -1), ("discharge_air_temperature", "mixed_air_temperature", -1),
                   ("terminal_unit_discharge_air_temperature", "terminal_unit_inlet_air_temperature", -1), ("discharge_air_temperature", "zone_air_temperature", -1)])
    if not (htg.notna().any() or clg.notna().any()):
        d.attrs["coil_perf_assessment"] = "no_coil_valve"
    elif not (rise.notna().any() or drop.notna().any()):
        d.attrs["coil_perf_assessment"] = "no_temperature_pair"
    else:
        d.attrs["coil_perf_assessment"] = "assessed"

    status = col("supply_fan_operating_status")
    supply_fan_command = norm_cmd(d["supply_fan_command"], representation="fraction") if "supply_fan_command" in d.columns else pd.Series(np.nan, index=d.index)
    fan_on = pd.Series(True, index=d.index)
    fan_on = fan_on.where(supply_fan_command.isna(), supply_fan_command > _gl36_value(p, "fan_on_min", None, FAN_ON_MIN))
    fan_on = fan_on.where(status.isna(), status > 0.05)
    flow = col("discharge_air_volume_flow_rate")
    flow_ok = flow.isna() | (flow > _f(p, "flow_on_min", 11.798675))

    heat = htg.notna() & (htg >= valve_open) & (clg.isna() | (clg <= valve_shut)) & rise.notna() & (rise < min_dt)
    cool = (clg.notna() & (clg >= valve_open) & (htg_v.isna() | (htg_v <= valve_shut)) & (rh_v.isna() | (rh_v <= valve_shut))
            & drop.notna() & (drop < min_dt))
    return (fan_on & flow_ok & (heat | cool)).fillna(False)

def fcu_clg_coil(d, p, poll):
    cool = norm_cmd(d["cooling_valve_position_command"])
    heat = norm_cmd(d["heating_valve_position_command"])
    rise = pd.to_numeric(d["discharge_air_temperature"], errors="coerce") - pd.to_numeric(
        d["zone_air_temperature"], errors="coerce"
    )
    return _fcu_fan_on(d) & cool.notna() & heat.notna() & (cool >= _f(p, "valve_open", 0.80)) & (heat <= 0.05) & (rise >= 0)


def fcu_valve_pass_htg(d, p, poll):
    heat = norm_cmd(d["heating_valve_position_command"])
    cool = norm_cmd(d["cooling_valve_position_command"])
    rise = pd.to_numeric(d["discharge_air_temperature"], errors="coerce") - pd.to_numeric(
        d["zone_air_temperature"], errors="coerce"
    )
    pass_delta = _param_si_delta_temp_to_series(
        d, "discharge_air_temperature", _f(p, "pass_delta", 3.0)
    )
    return _fcu_fan_on(d) & heat.notna() & cool.notna() & (heat <= 0.05) & (cool <= 0.05) & (rise > pass_delta)


def fcu_valve_pass_clg(d, p, poll):
    heat = norm_cmd(d["heating_valve_position_command"])
    cool = norm_cmd(d["cooling_valve_position_command"])
    drop = pd.to_numeric(d["zone_air_temperature"], errors="coerce") - pd.to_numeric(
        d["discharge_air_temperature"], errors="coerce"
    )
    pass_delta = _param_si_delta_temp_to_series(
        d, "discharge_air_temperature", _f(p, "pass_delta", 3.0)
    )
    return _fcu_fan_on(d) & heat.notna() & cool.notna() & (heat <= 0.05) & (cool <= 0.05) & (drop > pass_delta)


def fcu_damper_pos(d, p, poll):
    cmd = norm_cmd(d["damper_position_command"])
    pos = norm_cmd(d["damper_position"])
    return _fcu_fan_on(d) & (cmd >= _f(p, "command_min", 0.15)) & ((cmd - pos) > _f(p, "position_error", 0.15))


def fcu_co2_damper(d, p, poll):
    co2 = pd.to_numeric(d["zone_air_co2"], errors="coerce")
    cmd = norm_cmd(d["damper_position_command"])
    return _fcu_fan_on(d) & (co2 > _f(p, "co2_high_ppm", 1000.0)) & (co2 >= 300.0) & (cmd < _f(p, "damper_low", 0.10))


def fcu_deadband(d, p, poll):
    cool = pd.to_numeric(d["zone_cooling_air_temperature_setpoint"], errors="coerce")
    heat = pd.to_numeric(d["zone_heating_air_temperature_setpoint"], errors="coerce")
    band = _param_si_delta_temp_to_series(d, "zone_air_temperature", _f(p, "deadband", 1.0))
    return cool.notna() & heat.notna() & ((cool - heat) < band)


def fcu_mode_cycle(d, p, poll):
    heat = norm_cmd(d["heating_valve_position_command"])
    cool = norm_cmd(d["cooling_valve_position_command"])
    mode = pd.Series(0, index=d.index, dtype=int)
    mode = mode.mask(heat > _f(p, "mode_valve_min", 0.10), 1)
    mode = mode.mask(cool > _f(p, "mode_valve_min", 0.10), -1)
    active = mode.where(mode != 0).ffill().fillna(0)
    changes = ((active != active.shift()) & (active != 0) & (active.shift().fillna(0) != 0)).astype(int).cumsum()
    # Idle samples are omitted from the transition sequence and must not become
    # fault rows after the threshold is crossed.
    return (mode != 0) & (changes >= int(_f(p, "mode_changes", 4.0)))


def short_cycle(d, p, poll):
    """#1781 SHORT-CYCLE: starts in the trailing hour, or repeated short on-times, from proven run status (duty-aware)."""
    from open_fdd.rules.short_cycle import short_cycle_compute

    return short_cycle_compute(d, p, poll)


# ---------------------------------------------------------------------------
# Central plants
# ---------------------------------------------------------------------------


def chw1(d, p, poll):
    min_dt = _f(p, "min_dt", 2.222222)
    dt = d["return_chilled_water_temperature"] - d["supply_chilled_water_temperature"]
    return (
        d["supply_chilled_water_temperature"].notna()
        & d["return_chilled_water_temperature"].notna()
        & (dt < min_dt)
    )


def chw2(d, p, poll):
    margin = _f(p, "dp_margin", 15168.465)
    pmp_hi = _f(p, "pump_hi", 0.87)
    pump = norm_cmd(d["chilled_water_pump_command"], representation="fraction").fillna(0)
    return (
        d["chilled_water_pressure_delta"].notna() & d["chilled_water_pressure_delta_setpoint"].notna()
        & (d["chilled_water_pressure_delta"] < d["chilled_water_pressure_delta_setpoint"] - margin) & (pump >= pmp_hi)
    )


def chw3(d, p, poll):
    band = _f(p, "sp_band", 1.222222)
    pump = norm_cmd(d["chilled_water_pump_command"], representation="fraction").fillna(0)
    return (
        (pump > 0.01) & d["supply_chilled_water_temperature"].notna() & d["supply_chilled_water_temperature_setpoint"].notna()
        & ((d["supply_chilled_water_temperature"] < d["supply_chilled_water_temperature_setpoint"] - band) | (d["supply_chilled_water_temperature"] > d["supply_chilled_water_temperature_setpoint"] + band))
    )


def chw4(d, p, poll):
    flow_hi = _f(p, "flow_hi", 69.3992)
    pmp_hi = _f(p, "pump_hi", 0.87)
    pump = norm_cmd(d["chilled_water_pump_command"], representation="fraction").fillna(0)
    return d["chilled_water_volume_flow_rate"].notna() & (d["chilled_water_volume_flow_rate"] > flow_hi) & (pump >= pmp_hi)


# ---------------------------------------------------------------------------
# Heat pumps
# ---------------------------------------------------------------------------


def hp1(d, p, poll):
    min_sat = _f(p, "min_sat", 29.4444)
    zone_cold = _f(p, "zone_cold", 20.5556)
    fan = _fan(d)
    return (
        d["discharge_air_temperature"].notna() & d["zone_air_temperature"].notna() & (fan > FAN_ON_MIN)
        & (d["zone_air_temperature"] < zone_cold) & (d["discharge_air_temperature"] < min_sat)
    )


# ---------------------------------------------------------------------------
# Weather station
# ---------------------------------------------------------------------------


def wx1(d, p, poll):
    """OAT sample-to-sample spike; limit scales with the sample gap vs poll."""
    spike = _f(p, "spike_limit", 8.888889)
    s = pd.to_numeric(d["outdoor_air_intake_temperature"], errors="coerce")
    jump = s.diff().abs()
    if isinstance(d.index, pd.DatetimeIndex) and len(d.index) > 1:
        dt_s = d.index.to_series().diff().dt.total_seconds()
        scale = (dt_s / max(float(poll), 1.0)).fillna(1.0).clip(lower=1.0)
        return s.notna() & (jump > (spike * scale))
    return s.notna() & (jump > spike)


def wx2(d, p, poll):
    return d["wind_gust"].notna() & d["wind_speed"].notna() & (d["wind_gust"] < d["wind_speed"])


def cw_opt(d, p, poll):
    """Condenser-water not optimized vs wet-bulb (Stull) — CW colder than WB + approach."""
    if "supply_condenser_water_temperature" not in d.columns:
        return _false(d.index)
    wb = d["weather_service_air_wet_bulb_temperature"] if "weather_service_air_wet_bulb_temperature" in d.columns else None
    if wb is None or wb.notna().sum() == 0:
        return _false(d.index)
    approach = _f(p, "cw_approach", 3.888889)
    slack = _f(p, "cw_slack", 1.111111)
    # Over-cooled tower water: supply significantly below wet-bulb + design approach
    return (
        d["supply_condenser_water_temperature"].notna()
        & wb.notna()
        & (pd.to_numeric(d["supply_condenser_water_temperature"], errors="coerce") < (wb + approach - slack))
    )


def _tower_fan_full_mask(d: pd.DataFrame, p: dict) -> pd.Series:
    """True when tower / CW fan command is at/near full speed (0–1 or 0–100%)."""
    for role in ("cooling_tower_fan_command", "supply_fan_command"):
        if role in d.columns and d[role].notna().any():
            return norm_cmd(d[role], representation="fraction").fillna(0) > 0.5
    return _false(d.index)


def _cw_approach(d: pd.DataFrame) -> pd.Series:
    """Leaving CW minus web wet-bulb (°C difference)."""
    cw = pd.to_numeric(d["supply_condenser_water_temperature"], errors="coerce")
    wb = pd.to_numeric(d["weather_service_air_wet_bulb_temperature"], errors="coerce")
    return cw - wb


def cw_apr(d, p, poll):
    """High CW approach at full tower fan — sensors or tower degradation."""
    if "supply_condenser_water_temperature" not in d.columns:
        return _false(d.index)
    if "weather_service_air_wet_bulb_temperature" not in d.columns or d["weather_service_air_wet_bulb_temperature"].notna().sum() == 0:
        return _false(d.index)
    if not any(r in d.columns and d[r].notna().any() for r in ("cooling_tower_fan_command", "cooling_tower_fan_command", "supply_fan_command")):
        return _false(d.index)
    limit = _f(p, "approach_max", 4.444444)
    apr = _cw_approach(d)
    return (
        d["supply_condenser_water_temperature"].notna()
        & d["weather_service_air_wet_bulb_temperature"].notna()
        & _tower_fan_full_mask(d, p)
        & (apr > limit)
    )


def cw_fan_excess(d, p, poll):
    """Excess tower-fan energy — CW well above theoretical WB+approach at full fan."""
    if "supply_condenser_water_temperature" not in d.columns:
        return _false(d.index)
    if "weather_service_air_wet_bulb_temperature" not in d.columns or d["weather_service_air_wet_bulb_temperature"].notna().sum() == 0:
        return _false(d.index)
    if not any(r in d.columns and d[r].notna().any() for r in ("cooling_tower_fan_command", "cooling_tower_fan_command", "supply_fan_command")):
        return _false(d.index)
    approach = _f(p, "cw_approach", 3.888889)
    excess = _f(p, "excess_beyond_approach", 2.777778)
    apr = _cw_approach(d)
    return (
        d["supply_condenser_water_temperature"].notna()
        & d["weather_service_air_wet_bulb_temperature"].notna()
        & _tower_fan_full_mask(d, p)
        & (apr > (approach + excess))
    )


def oat_vs_meteo(d, p, poll):
    """BAS outdoor-air sensor disagrees with Open-Meteo dry bulb by more than the threshold."""
    if "weather_service_air_temperature" not in d.columns and "web_oat_native_frame" not in d.attrs:
        return _false(d.index)
    err = _f(p, "oat_err", 2.777778)
    cadence = _f(p, "web_cadence_seconds", 1200.0)
    margin = _f(p, "web_asof_margin_seconds", 300.0)
    bound_s = cadence + margin
    bas = pd.to_numeric(d["outdoor_air_intake_temperature"], errors="coerce")
    if not isinstance(d.index, pd.DatetimeIndex):
        web = pd.to_numeric(d["weather_service_air_temperature"], errors="coerce")
        return bas.notna() & web.notna() & (bas.sub(web).abs() > err)
    web_native = d.attrs.get("web_oat_native_frame")
    if isinstance(web_native, pd.DataFrame) and "weather_service_air_temperature" in web_native.columns:
        web_src = web_native[["weather_service_air_temperature"]].sort_index()
    else:
        web_src = pd.DataFrame({"weather_service_air_temperature": pd.to_numeric(d["weather_service_air_temperature"], errors="coerce")})
        web_src.index = d.index
        web_src = web_src.dropna().sort_index()
    left = pd.DataFrame({"outdoor_air_intake_temperature": bas}).sort_index()
    merged = pd.merge_asof(
        left,
        web_src,
        left_index=True,
        right_index=True,
        direction="backward",
        tolerance=pd.Timedelta(seconds=bound_s),
    )
    web_aligned = merged["weather_service_air_temperature"]
    assessed = bas.notna() & web_aligned.notna()
    return assessed & (bas.sub(web_aligned).abs() > err)


# ---------------------------------------------------------------------------
# Trim & respond advisory
# ---------------------------------------------------------------------------


def trim1(d, p, poll):
    duct_hi = _f(p, "duct_hi", 335.934)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["discharge_air_static_pressure"].notna() & d["discharge_air_static_pressure_reset_request_count"].notna()
        & (d["discharge_air_static_pressure"] > duct_hi) & (d["discharge_air_static_pressure_reset_request_count"] < req_lo)
    )


def trim3(d, p, poll):
    hwst_hi = _f(p, "hwst_hi", 71.1111)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["supply_hot_water_temperature"].notna() & d["hot_water_reset_request_count"].notna()
        & (d["supply_hot_water_temperature"] > hwst_hi) & (d["hot_water_reset_request_count"] <= req_lo)
    )


def trim4(d, p, poll):
    chw_lo = _f(p, "chw_lo", 7.222222)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["supply_chilled_water_temperature"].notna() & d["chilled_water_reset_request_count"].notna()
        & (d["supply_chilled_water_temperature"] < chw_lo) & (d["chilled_water_reset_request_count"] <= req_lo)
    )


# ---------------------------------------------------------------------------
# Extended families
# ---------------------------------------------------------------------------


def reset1(d, p, poll):
    """SAT SP not tracking the OA reset curve."""
    err = _f(p, "reset_err", 1.666667)
    intercept = _f(p, "reset_sat_at_ref", 11.111111)
    slope = _f(p, "reset_slope", 0.25)
    oat_ref = _f(p, "reset_oat_ref", 18.333333)
    oat = pd.to_numeric(d["outdoor_air_intake_temperature"], errors="coerce")
    discharge_air_temperature_setpoint = pd.to_numeric(d["discharge_air_temperature_setpoint"], errors="coerce")
    expected = intercept + slope * (oat - oat_ref)
    fan = pd.Series(True, index=d.index)
    if "supply_fan_operating_status" in d.columns and d["supply_fan_operating_status"].notna().any():
        fan = as_bool(d["supply_fan_operating_status"])
    elif "supply_fan_command" in d.columns:
        fan = norm_cmd(d["supply_fan_command"], representation="fraction").fillna(0) > 0.05
    return discharge_air_temperature_setpoint.notna() & oat.notna() & fan.fillna(False) & ((discharge_air_temperature_setpoint - expected).abs() > err)


def sched1(d, p, poll):
    """Unoccupied fan runtime; optional zone comfort band when zone_air_temperature is mapped.

    Portable occupancy: literal ``unoccupied`` (case-insensitive) **or** numeric /
    boolean falsey values (``0``, ``0.0``, ``False``). String ``"1"`` / occupied
    labels are treated as occupied.
    """
    if "occupancy_status" not in d or "supply_fan_operating_status" not in d:
        return _false(d.index)
    occ_raw = d["occupancy_status"]
    occ_str = occ_raw.astype(str).str.strip().str.lower()
    label_unocc = occ_str.isin(
        {"unoccupied", "unocc", "off", "false", "night", "standby", "setback", "no"}
    )
    occ_num = pd.to_numeric(occ_raw, errors="coerce")
    numeric_unocc = occ_num.notna() & (occ_num <= 0.05)
    unoccupied = label_unocc | numeric_unocc
    base = unoccupied & as_bool(d["supply_fan_operating_status"])
    if "zone_air_temperature" not in d.columns or d["zone_air_temperature"].notna().sum() == 0:
        return base
    lo = _f(p, "comfort_low", 21.111111)
    hi = _f(p, "comfort_high", 23.888889)
    zt = pd.to_numeric(d["zone_air_temperature"], errors="coerce")
    in_band = zt.notna() & (zt >= lo) & (zt <= hi)
    return base & in_band


def cmd1(d, p, poll):
    cmd_on = norm_cmd(d["supply_fan_command"], representation="fraction").fillna(0) >= 0.05
    return d["supply_fan_operating_status"].notna() & (cmd_on != as_bool(d["supply_fan_operating_status"]))


def oa1(d, p, poll):
    min_oa = _f(p, "min_oa_frac", 15.0)
    guard = _f(p, "oat_rat_guard", 1.2222222222222223)
    oa_frac = (d["mixed_air_temperature"] - d["return_air_temperature"]) / (d["outdoor_air_intake_temperature"] - d["return_air_temperature"]).replace(0, np.nan)
    fan = _fan(d)
    return (
        (fan > FAN_ON_MIN) & d["outdoor_air_intake_temperature"].notna() & d["return_air_temperature"].notna() & d["mixed_air_temperature"].notna()
        & ((d["return_air_temperature"] - d["outdoor_air_intake_temperature"]).abs() > guard) & (oa_frac * 100.0 < min_oa)
    )


def dmp1(d, p, poll):
    leak_delta = _f(p, "leak_delta", 1.111111)
    dmp = norm_cmd(d["outdoor_air_intake_damper_position_command"]).fillna(0)
    return d["outdoor_air_intake_temperature"].notna() & d["mixed_air_temperature"].notna() & (dmp <= 0.05) & (d["mixed_air_temperature"].sub(d["outdoor_air_intake_temperature"]).abs() < leak_delta)


def vlv1(d, p, poll):
    """Cooling valve leak: valve closed AND (SAT low vs SP or SAT low vs MAT).

    Fan proven-on is enforced by the VLV-1 operational gate when supply_fan_operating_status/supply_fan_command exist.
    """
    sat_err = _f(p, "sat_err", 1.111111)
    mat_delta = _f(p, "mat_leak_delta", 1.111111)
    clg = norm_cmd(d["cooling_valve_position_command"]).fillna(0)
    closed = clg <= 0.05
    discharge_air_temperature = pd.to_numeric(d["discharge_air_temperature"], errors="coerce")
    discharge_air_temperature_setpoint = pd.to_numeric(d["discharge_air_temperature_setpoint"], errors="coerce")
    below_sp = discharge_air_temperature.notna() & discharge_air_temperature_setpoint.notna() & (discharge_air_temperature < discharge_air_temperature_setpoint - sat_err)
    below_mat = pd.Series(False, index=d.index)
    if "mixed_air_temperature" in d.columns and d["mixed_air_temperature"].notna().any():
        mixed_air_temperature = pd.to_numeric(d["mixed_air_temperature"], errors="coerce")
        below_mat = discharge_air_temperature.notna() & mixed_air_temperature.notna() & (discharge_air_temperature < mixed_air_temperature - mat_delta)
    return closed & (below_sp | below_mat)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

RULES: list[CookbookRule] = [
    # --- Sensor validation sweep (applies to every sensor present) ---
    CookbookRule(
        "SV-RANGE", "Sensor out of hard range", "sensor",
        ["ahu", "vav", "chiller", "boiler", "weather", "zone_other", "heatpump"], [],
        "Any modeled sensor reads outside its physical hard range (e.g. OAT −51–54 °C, SAT −1–66 °C, CHWS −1–27 °C).",
        _sweep_range,
        params=[
            CookbookParam("range_scale_temperature", "Temp range scale", "x", 0.5, 2.0, 0.1, 1.0, direction="fewer"),
            CookbookParam("range_scale_humidity", "Humidity range scale", "x", 0.5, 2.0, 0.1, 1.0, direction="fewer"),
            CookbookParam("range_scale_pressure", "Pressure range scale", "x", 0.5, 2.0, 0.1, 1.0, direction="fewer"),
            CONFIRM_PARAM(),
            CookbookParam("max_silence_hours", "Max sensor silence", "h", 0.25, 12.0, 0.25, 0.5),
        ],
        sensor_sweep=True,
        confirm_seconds=300,
    ),
    CookbookRule(
        "SV-FLATLINE", "Sensor flatline (stuck)", "sensor",
        ["ahu", "vav", "chiller", "boiler", "weather", "zone_other", "heatpump"], [],
        "Sensor value unchanged (Δ ≤ tolerance) across the flatline window — stuck / frozen sensor.",
        _sweep_flatline,
        params=[
            CookbookParam("flatline_tol", "Flatline tolerance", "°C", 0.011111, 0.555556, 0.011111, 0.055556, direction="stricter"),
            CookbookParam("flatline_hours", "Flatline window", "h", 0.25, 8.0, 0.25, 1.0, direction="fewer"),
            CookbookParam("max_silence_hours", "Max sensor silence", "h", 0.25, 12.0, 0.25, 0.5),
            CookbookParam("require_operational_gate", "Require operational gate", "bool", 0.0, 1.0, 1.0, 1.0),
            CONFIRM_PARAM(),
        ], sensor_sweep=True, confirm_seconds=300,
    ),
    CookbookRule(
        "SV-SPIKE", "Sensor rate-of-change spike", "sensor",
        ["ahu", "vav", "chiller", "boiler", "weather", "zone_other", "heatpump"], [],
        "Sample-to-sample jump exceeds the physical spike limit for the sensor type.",
        _sweep_spike, params=[
            CookbookParam("minimum_active_coverage_pct", "Minimum active coverage", "%", 0.0, 100.0, 1.0, 5.0),
            CookbookParam("require_operational_gate", "Require operational gate", "bool", 0.0, 1.0, 1.0, 1.0),
            CookbookParam("spike_scale", "Spike limit scale (global)", "x", 0.25, 3.0, 0.25, 1.0, direction="fewer"),
            CookbookParam("spike_scale_temperature", "Temp spike scale", "x", 0.25, 3.0, 0.25, 1.0, direction="fewer"),
            CookbookParam("spike_scale_humidity", "Humidity spike scale", "x", 0.25, 3.0, 0.25, 1.0, direction="fewer"),
            CookbookParam("spike_scale_pressure", "Pressure spike scale", "x", 0.25, 3.0, 0.25, 1.0, direction="fewer"),
            CONFIRM_PARAM(),
            CookbookParam("max_silence_hours", "Max sensor silence", "h", 0.25, 12.0, 0.25, 0.5),
        ], sensor_sweep=True, confirm_seconds=300,
    ),
    CookbookRule(
        "SV-STALE", "Stale data (no fresh samples for longer than the stale threshold)", "sensor",
        ["ahu", "vav", "chiller", "boiler", "weather", "zone_other", "heatpump"], [],
        "A sensor sent no valid sample for longer than the stale threshold (gap or missing series); not gated by run proof.",
        _sweep_stale, params=[
            CookbookParam("stale_after_hours", "Stale after", "h", 0.25, 12.0, 0.25, 0.5),
        ], sensor_sweep=True, confirm_seconds=0,
    ),
    CookbookRule(
        "SV-RATE",
        "Context-aware sensor rate of change",
        "sensor",
        ["ahu", "vav", "chiller", "boiler", "weather", "zone_other", "heatpump"],
        [],
        "Implausible sustained rate-of-change for mapped sensors. Thresholds depend on "
        "quantity, location, and operating state (steady vs startup/shutdown transient). "
        "Engineering screening defaults — tune per site. Alias: SV-SLEW. "
        "Distinct from SV-SPIKE (one-sample jump), SV-RANGE, SV-FLATLINE, and PID-HUNT-1.",
        _sv_rate_compute,
        params=[
            CookbookParam("persistence_min", "Fault persistence", "min", 5.0, 60.0, 1.0, 10.0),
            CookbookParam("transition_window_min", "Transition window", "min", 5.0, 60.0, 5.0, 20.0),
            CookbookParam("max_gap_hours", "Max sample gap", "h", 0.25, 6.0, 0.25, 2.0),
            CookbookParam("design_flow", "Design flow (flow profiles)", "L/s", 0.0, 47194.7, 47.1947, 0.0),
            CookbookParam("sensor_span", "Sensor span (flow/pressure)", "eng", 0.0, 100000.0, 10.0, 0.0),
            CONFIRM_PARAM(),
        ],
        sensor_sweep=True,
        confirm_seconds=600,
    ),
    CookbookRule(
        "PID-HUNT-1", "Suspected control-output hunting", "control",
        ["ahu", "vav", "chiller", "boiler", "heatpump"], [],
        "Rolling 1h total variation of any 0–100% control output (dampers, valves, fan speeds, "
        "heat/cool cmds) with span ≥20%, TV ≥500 %·pts, ≥2.5 equivalent cycles, ≥4 reversals — "
        "suspected loop hunting (not proof of bad PID alone).",
        _pid_hunt_1,
        params=[
            CookbookParam("change_deadband_pct", "Ignore changes below", "% out", 0.0, 10.0, 0.5, 1.0),
            CookbookParam("minimum_span_pct", "Minimum observed span", "% out", 5.0, 100.0, 5.0, 20.0),
            CookbookParam("total_variation_fault_pct", "Total travel threshold", "%/h", 50.0, 2000.0, 50.0, 500.0),
            CookbookParam("minimum_equivalent_cycles", "Min equivalent cycles", "cyc/h", 0.5, 20.0, 0.5, 2.5),
            CookbookParam("minimum_reversals", "Min direction reversals", "count", 1, 40, 1, 4),
            CookbookParam("minimum_coverage_pct", "Minimum data coverage", "%", 25.0, 100.0, 5.0, 80.0),
            CONFIRM_PARAM(),
        ],
        optional_roles=["operating_mode_status"],
        control_output_sweep=True,
        confirm_seconds=0,
    ),

    # --- AHU GL36 (FC1–FC15) ---
    CookbookRule("FC1", "Duct static below SP at full fan (GL36 A)", "ahu", ["ahu"],
        ["discharge_air_static_pressure", "discharge_air_static_pressure_setpoint", "supply_fan_speed_command"],
        "DSP < DSPSP − εDSP AND supply_fan_speed_command ≥ 100% − εVFDSPD.",
        fc1, params=[
            CookbookParam("eps_dsp", "Duct-static error εDSP", "Pa", 0.0, 124.42, 2.4884, 29.8608),
            CookbookParam("eps_vfd_spd", "VFD speed error εVFDSPD (fraction; G36-2018 lists 0.05)", "frac", 0.0, 0.5, 0.01, 0.13),
            CookbookParam("duct_static_err", "Legacy duct-static error (sets εDSP)", "Pa", 0.0, 124.42, 2.4884, 29.8608),
            CookbookParam("fan_hi", "Legacy fan-high threshold (sets εVFDSPD)", "frac", 0.5, 1.0, 0.01, 0.87),
            MODE_DELAY_PARAM(),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("FC2", "MAT below OAT/RAT envelope (GL36 B)", "ahu", ["ahu"],
        ["mixed_air_temperature", "outdoor_air_intake_temperature", "return_air_temperature", "supply_fan_command"],
        "MATavg + εMAT < min(RATavg − εRAT, OATavg − εOAT).",
        fc2, params=[
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            EPS_TEMP_PARAM("eps_rat", "RAT sensor error εRAT"),
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT"),
            LEGACY_MIX_PARAM(), FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC3", "MAT above OAT/RAT envelope (GL36 C)", "ahu", ["ahu"],
        ["mixed_air_temperature", "outdoor_air_intake_temperature", "return_air_temperature", "supply_fan_command"],
        "MATavg − εMAT > max(RATavg + εRAT, OATavg + εOAT).",
        fc3, params=[
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            EPS_TEMP_PARAM("eps_rat", "RAT sensor error εRAT"),
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT"),
            LEGACY_MIX_PARAM(), FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC4", "PID hunting (operating-state oscillation)", "ahu", ["ahu"],
        ["outdoor_air_intake_damper_position_command", "cooling_valve_position_command", "supply_fan_command"],
        "ΔOS > ΔOSmax during the prior 60-minute moving window.",
        fc4, params=[
            CookbookParam("delta_os_max", "Max mode changes/hr ΔOSmax (GL36 default 7)", "count", 1, 30, 1, 5, direction="fewer"),
            MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=3600),
    CookbookRule("FC5", "SAT cold when heating commanded (GL36 D)", "ahu", ["ahu"],
        ["discharge_air_temperature", "mixed_air_temperature", "supply_fan_command", "heating_valve_position_command"],
        "SATavg + εSAT ≤ MATavg − εMAT + ΔTSF while heating is commanded.",
        fc5, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            DELTA_TSF_PARAM(),
            CookbookParam("htg_on_min", "Heating-command ON threshold", "frac", 0.0, 0.25, 0.01, 0.01),
            LEGACY_MIX_PARAM(), FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC6", "Estimated OA fraction mismatch", "ahu", ["ahu"],
        ["mixed_air_temperature", "outdoor_air_intake_temperature", "return_air_temperature", "terminal_unit_discharge_air_total_volume_flow_rate"],
        "|RATavg−OATavg| ≥ ΔTmin AND |estimated OA% − design min OA%| > εF.",
        fc6, params=[
            CookbookParam("eps_airflow", "Airflow error εF (GL36 default 30%)", "frac", 0.05, 1.0, 0.01, 0.15),
            CookbookParam("delta_t_min", "Minimum |OAT−RAT| ΔTmin", "Δ°C", 0.0, 16.666667, 0.277778, 2.777778),
            CookbookParam("airflow_err", "Legacy OA-fraction error (sets εF)", "frac", 0.05, 1.0, 0.01, 0.15),
            CookbookParam("oat_rat_delta_min", "Legacy OAT/RAT guard (sets ΔTmin)", "°C", 0.0, 16.666667, 0.277778, 2.777778),
            CookbookParam("min_flow_design", "Design minimum outdoor airflow", "L/s", 0.0, 94389.4, 47.1947, 2359.735),
            FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC7", "SAT low with full heating (GL36 E)", "ahu", ["ahu"],
        ["discharge_air_temperature", "discharge_air_temperature_setpoint", "supply_fan_command", "heating_valve_position_command"],
        "SATavg < SATSP − εSAT AND HC ≥ full-heating threshold.",
        fc7, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            CookbookParam("sat_err", "Legacy SAT error (sets εSAT)", "Δ°C", 0.0, 5.555556, 0.138889, 0.555556),
            CookbookParam("htg_full_min", "Full-heating threshold (fraction)", "frac", 0.5, 1.0, 0.01, 0.90),
            FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC8", "SAT/MAT mismatch in economizer (GL36)", "ahu", ["ahu"],
        ["discharge_air_temperature", "mixed_air_temperature", "outdoor_air_intake_damper_position_command", "cooling_valve_position_command"],
        "|SATavg − ΔTSF − MATavg| > √(εSAT² + εMAT²) in OS#2.",
        fc8, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), CLG_INACTIVE_PARAM(),
            LEGACY_MIX_PARAM(), LEGACY_SUPPLY_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC9", "OAT too warm for free cooling (GL36 G)", "ahu", ["ahu"],
        ["outdoor_air_intake_temperature", "discharge_air_temperature_setpoint", "outdoor_air_intake_damper_position_command", "cooling_valve_position_command"],
        "OATavg − εOAT > SATSP − ΔTSF + εSAT in OS#2.",
        fc9, params=[
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT"),
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), CLG_INACTIVE_PARAM(),
            LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC10", "OAT/MAT mismatch + mech cooling (GL36 H)", "ahu", ["ahu"],
        ["mixed_air_temperature", "outdoor_air_intake_temperature", "outdoor_air_intake_damper_position_command", "cooling_valve_position_command"],
        "|MATavg − OATavg| > √(εMAT² + εOAT²) in OS#3.",
        fc10, params=[
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT"),
            ECON_FULL_PARAM(), CLG_ON_PARAM(), LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC11", "OAT/MAT mismatch economizer-only (GL36 I)", "ahu", ["ahu"],
        ["outdoor_air_intake_temperature", "discharge_air_temperature_setpoint", "outdoor_air_intake_damper_position_command", "cooling_valve_position_command"],
        "OATavg + εOAT < SATSP − ΔTSF − εSAT in OS#3.",
        fc11, params=[
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT"),
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            DELTA_TSF_PARAM(), ECON_FULL_PARAM(), CLG_ON_PARAM(),
            LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC12", "SAT above blend in cooling (GL36 J)", "ahu", ["ahu"],
        ["discharge_air_temperature", "mixed_air_temperature", "outdoor_air_intake_damper_position_command", "cooling_valve_position_command"],
        "SATavg − εSAT − ΔTSF ≥ MATavg + εMAT in OS#3/OS#4.",
        fc12, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), ECON_FULL_PARAM(), CLG_ON_PARAM(),
            LEGACY_MIX_PARAM(), LEGACY_SUPPLY_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC13", "SAT above SP at full cooling (GL36 K)", "ahu", ["ahu"],
        ["discharge_air_temperature", "discharge_air_temperature_setpoint", "outdoor_air_intake_damper_position_command", "cooling_valve_position_command"],
        "SATavg > SATSP + εSAT AND CC ≥ full-cooling threshold in OS#3/OS#4.",
        fc13, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            CookbookParam("sat_err", "Legacy SAT error (sets εSAT)", "Δ°C", 0.0, 5.555556, 0.138889, 0.555556),
            CookbookParam("clg_full_min", "Full-cooling threshold (fraction)", "frac", 0.5, 1.0, 0.01, 0.9),
            ECON_MIN_PARAM(), ECON_FULL_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC14", "CHW coil ΔT when inactive (GL36 L)", "ahu", ["ahu"],
        ["cooling_coil_inlet_air_temperature", "cooling_coil_outlet_air_temperature", "outdoor_air_intake_damper_position_command", "cooling_valve_position_command"],
        "Cooling-coil ΔT ≥ √(εCCET² + εCCLT²) + ΔTSF while coil should be inactive.",
        fc14, params=[
            EPS_TEMP_PARAM("eps_ccet", "Cooling-coil entering sensor error εCCET"),
            EPS_TEMP_PARAM("eps_cclt", "Cooling-coil leaving sensor error εCCLT"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), CLG_INACTIVE_PARAM(),
            CookbookParam("htg_on_min", "Heating-command ON threshold", "frac", 0.0, 0.25, 0.01, 0.01),
            LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC15", "HW coil ΔT when inactive (GL36 M)", "ahu", ["ahu"],
        ["heating_coil_inlet_air_temperature", "heating_coil_outlet_air_temperature", "outdoor_air_intake_damper_position_command", "cooling_valve_position_command"],
        "Heating-coil ΔT ≥ √(εHCET² + εHCLT²) + ΔTSF while coil should be inactive.",
        fc15, params=[
            EPS_TEMP_PARAM("eps_hcet", "Heating-coil entering sensor error εHCET"),
            EPS_TEMP_PARAM("eps_hclt", "Heating-coil leaving sensor error εHCLT"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), ECON_FULL_PARAM(),
            CLG_INACTIVE_PARAM(), CLG_ON_PARAM(), LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),

    # --- AHU additional patterns ---
    CookbookRule("AHU-SATDEV", "SAT deviation from setpoint", "ahu", ["ahu"],
        ["discharge_air_temperature", "discharge_air_temperature_setpoint"], "|SAT − SAT SP| > 2.8 Δ°C.",
        ahu_sat_dev, params=[CookbookParam("sat_dev_err", "SAT deviation", "Δ°C", 0.555556, 8.333333, 0.277778, 2.777778, direction="fewer"), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("AHU-DUCTHI", "Duct static pressure high", "ahu", ["ahu"],
        ["discharge_air_static_pressure", "discharge_air_static_pressure_setpoint"],
        "Duct static > static SP + margin. Evaluates when fan is proven on OR duct static "
        "itself exceeds pressure_on_min (catches high static with fan-status off).",
        ahu_duct_high,
        params=[
            CookbookParam("duct_high_margin", "High margin", "Pa", 12.442, 248.84, 12.442, 62.21, direction="fewer"),
            CookbookParam("pressure_on_min", "Pressure-on evidence", "Pa", 12.442, 248.84, 12.442, 49.768, direction="stricter"),
            CONFIRM_PARAM(),
        ],
        confirm_seconds=300),
    CookbookRule("AHU-SIMUL", "Heating and cooling simultaneous", "ahu", ["ahu"],
        ["heating_valve_position_command", "cooling_valve_position_command"], "Heating valve > 10% AND cooling valve > 10% at once.",
        ahu_simul_heat_cool, params=[CookbookParam("valve_open_pct", "Valve open threshold", "frac", 0.05, 0.5, 0.01, 0.10), CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("OAT-METEO", "BAS outdoor-air sensor vs Open-Meteo", "ahu", ["ahu"],
        ["outdoor_air_intake_temperature", "weather_service_air_temperature"], "BAS OAT sensor differs from Open-Meteo dry bulb by more than 2.8 Δ°C.",
        oat_vs_meteo, params=[
            CookbookParam("oat_err", "Max OAT disagreement", "°C", 1.111111, 11.111111, 0.277778, 2.777778, direction="fewer"),
            CookbookParam("web_cadence_seconds", "Web weather cadence", "sec", 300.0, 7200.0, 300.0, 1200.0),
            CookbookParam("web_asof_margin_seconds", "Web as-of margin", "sec", 0.0, 1800.0, 60.0, 300.0),
            CONFIRM_PARAM()], confirm_seconds=900),

    # --- Economizer & ventilation ---
    CookbookRule("ECON-1", "Economizer stuck closed", "ahu", ["ahu"],
        ["supply_fan_command", "outdoor_air_intake_damper_position_command", "outdoor_air_intake_temperature"], "Fan on, OA damper < 5%, OAT > 12.8 °C (should be economizing).",
        econ1, params=[CookbookParam("econ1_oat_min", "Favorable OAT", "°C", 7.222222, 21.111111, 0.555556, 12.777778), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("ECON-2", "Economizing when outdoor unfavorable", "ahu", ["ahu"],
        ["outdoor_air_intake_temperature", "outdoor_air_intake_damper_position_command"], "OAT > 17.2 °C AND OA damper > 42% (should be at minimum).",
        econ2, params=[
            CookbookParam("econ2_oat_hi", "OAT high cutoff", "°C", 12.777778, 26.666667, 0.555556, 17.222222),
            CookbookParam("econ2_damper", "Damper open frac", "frac", 0.2, 0.9, 0.02, 0.42),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule(
        "ECON-3",
        "Mech cooling without integrated economizer",
        "ahu",
        ["ahu"],
        ["outdoor_air_intake_damper_position_command", "cooling_valve_position_command"],
        "Web free-cooling opportunity: 15.6 °C ≤ dry-bulb < 22.2 °C AND dewpoint < 15.6 °C "
        "(dewpoint from web sensor or calculated from web DB+RH). Fault when cooling valve is "
        "open while OA damper is below the integrated-economizer threshold (default 90%). "
        "No BAS OAT fallback. Screenable engineering defaults — not code limits.",
        # placeholder; engine substitutes weather-aware econ3_compute
        econ2,
        params=[
            CookbookParam("econ3_db_min", "Free-cool OA dry-bulb min", "°C", 10.0, 20.0, 0.555556, 15.555556),
            CookbookParam("econ3_db_max", "Free-cool OA dry-bulb max", "°C", 18.333333, 26.666667, 0.555556, 22.222222),
            CookbookParam("econ3_dp_max", "Free-cool OA dew point max", "°C", 7.222222, 20.0, 0.555556, 15.555556),
            CookbookParam("econ3_damper_hi", "Integrated economizer damper", "frac", 0.5, 1.0, 0.02, 0.90, direction="fewer"),
            CONFIRM_PARAM(),
        ],
        optional_roles=["weather_service_air_temperature", "weather_service_air_dew_point_temperature", "weather_service_air_relative_humidity"],
        confirm_seconds=300,
    ),
    CookbookRule("ECON-4", "Low estimated OA fraction", "ahu", ["ahu"],
        ["mixed_air_temperature", "return_air_temperature", "outdoor_air_intake_temperature", "supply_fan_command"], "Fan on, |RAT−OAT| > 1.2 Δ°C, estimated OA fraction < 21%.",
        econ4, params=[CookbookParam("oa_min_pct", "Min OA fraction", "%", 5.0, 40.0, 1.0, 21.0, direction="stricter"), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("ECON-5", "Preheat over-conditioning", "ahu", ["ahu"],
        ["preheat_heating_coil_outlet_air_temperature", "discharge_air_temperature_setpoint", "outdoor_air_intake_temperature", "heating_valve_position_command"], "Preheat leaving air > 1.2°C above target while preheat active.",
        econ5, params=[CookbookParam("preheat_over", "Preheat over ΔT", "Δ°C", 0.277778, 4.444444, 0.055556, 1.222222, direction="fewer"), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule(
        "ECON-6",
        "Economizing in freezing weather",
        "ahu",
        ["ahu"],
        ["outdoor_air_intake_damper_position_command"],
        "Web dry-bulb < −3.9°C AND OA damper above winter min-OA ceiling (default 25%). "
        "AHU should be at minimum OA in cold weather.",
        __import__("open_fdd.rules.economizer_weather", fromlist=["econ6_compute"]).econ6_compute,
        params=[
            CookbookParam("econ6_oat_max", "Winter OAT ceiling", "°C", -9.444444, 4.444444, 0.555556, -3.888889),
            CookbookParam("econ6_damper_max", "Winter min-OA damper", "frac", 0.05, 0.5, 0.01, 0.25),
            CONFIRM_PARAM(),
        ],
        optional_roles=["weather_service_air_temperature"],
        confirm_seconds=600,
    ),
    CookbookRule(
        "ECON-7",
        "Economizer OK but not economizing",
        "ahu",
        ["ahu"],
        ["outdoor_air_intake_damper_position_command"],
        "Economizer-OK web weather: dew point < 15.6°C AND dry-bulb < 22.2°C (above a "
        "1.7°C freeze-guard floor; dewpoint from web sensor or calculated from web DB+RH). "
        "Fault when there is cooling demand (cooling valve open or proven DX/chiller "
        "cooling) but the OA damper stays below the economizing threshold (default 50%). "
        "Expected: economizer-only below 15.6°C DB (MECH-OAT-1) and mech + integrated "
        "economizer in the 15.6–22.2°C band (ECON-3). All temperature thresholds are SI.",
        __import__("open_fdd.rules.economizer_weather", fromlist=["econ7_compute"]).econ7_compute,
        params=[
            CookbookParam("econ7_db_min", "Econ-OK dry-bulb floor (freeze guard)", "°C", -6.666667, 10.0, 0.555556, 1.666667),
            CookbookParam("econ7_db_max", "Econ-OK dry-bulb max", "°C", 18.333333, 26.666667, 0.555556, 22.222222),
            CookbookParam("econ7_dp_max", "Econ-OK dew point max", "°C", 7.222222, 20.0, 0.555556, 15.555556),
            CookbookParam("econ7_damper_min", "Economizing damper threshold", "frac", 0.2, 0.9, 0.02, 0.50, direction="stricter"),
            CONFIRM_PARAM(),
        ],
        optional_roles=[
            "weather_service_air_temperature",
            "weather_service_air_dew_point_temperature",
            "weather_service_air_relative_humidity",
            "cooling_valve_position_command",
            "compressor_operating_status",
        ],
        confirm_seconds=600,
    ),
    CookbookRule(
        "MECH-OAT-1",
        "Mechanical cooling below 15.6 °C web OAT",
        "ahu",
        ["ahu", "chiller", "heatpump"],
        [],
        "Proven DX/chiller mechanical cooling while web dry-bulb < 15.6 °C. "
        "Uses compressor/chiller/pump/amps/power proof — not AHU cooling-valve alone. "
        "Below 15.6 °C is outside the free-cool + integrated economizer band.",
        __import__("open_fdd.rules.economizer_weather", fromlist=["mech_oat1_compute"]).mech_oat1_compute,
        params=[
            CookbookParam("mech_oat_max", "Mech-cool OAT ceiling", "°C", 7.222222, 18.333333, 0.555556, 15.555556, direction="stricter"),
            CONFIRM_PARAM(),
        ],
        optional_roles=[
            "weather_service_air_temperature",
            "compressor_operating_status",
            "chiller_operating_status",
            "chilled_water_pump_operating_status",
        ],
        confirm_seconds=600,
    ),
    CookbookRule(
        "HW-OAT-1",
        "Hot-water plant proven on above 18.3 °C web OAT",
        "plant",
        ["boiler"],
        ["weather_service_air_temperature"],
        "Pump on, or supply above 43.3 °C, with web dry-bulb above 18.3 °C.",
        __import__("open_fdd.rules.economizer_weather", fromlist=["hw_oat1_compute"]).hw_oat1_compute,
        params=[
            CookbookParam("hw_oat_min", "HW lockout OAT", "°C", 12.777778, 23.888889, 0.555556, 18.333333, direction="fewer"),
            CookbookParam("hw_on_min", "HW supply running cut", "°C", 32.222222, 60.0, 0.555556, 43.333333, direction="fewer"),
            CONFIRM_PARAM(15.0),
        ],
        optional_roles=["pump_operating_status", "supply_hot_water_temperature"],
        confirm_seconds=900,
    ),
    CookbookRule(
        "CHW-NOLOAD-1",
        "Chiller running with no building load",
        "plant",
        ["chiller"],
        [],
        "Chiller/plant proven running while building load is satisfied: all mapped zones inside "
        "comfort band OR all mapped AHU SAT within sat_band of setpoint. Default confirm 30 min.",
        __import__("open_fdd.rules.economizer_weather", fromlist=["chw_noload1_compute"]).chw_noload1_compute,
        params=[
            CookbookParam("comfort_low", "Comfort low", "°C", 15.555556, 25.555556, 0.277778, 21.111111),
            CookbookParam("comfort_high", "Comfort high", "°C", 20.0, 29.444444, 0.277778, 23.888889),
            CookbookParam("sat_band", "AHU SAT≈SP band", "Δ°C", 0.277778, 3.333333, 0.277778, 1.111111),
            CookbookParam("confirm_min", "Fault confirm delay", "min", 0.0, 60.0, 1.0, 30.0),
        ],
        optional_roles=[
            "chiller_operating_status",
            "chilled_water_pump_operating_status",
            "compressor_operating_status",
            "zone_load_satisfied_status",
            "air_handling_unit_load_satisfied_status",
        ],
        confirm_seconds=1800,
    ),

    # --- Fan coils / standalone zone controllers ---
    CookbookRule("FCU-SENSOR-NULL", "Missing FCU zone sensor", "fcu", ["zone_other", "general", "ahu"],
        ["zone_air_temperature_setpoint"],
        "Own zone setpoint is present while zone temperature is null for at least 90% of the window.",
        fcu_sensor_null, params=[
            CookbookParam("null_fraction", "Null fraction", "frac", 0.5, 1.0, 0.05, 0.90),
            CONFIRM_PARAM()], optional_roles=["zone_air_temperature"], confirm_seconds=0),
    CookbookRule("FCU-HTG-COIL", "FCU heating coil under-delivery", "fcu", ["zone_other", "general", "ahu"],
        ["discharge_air_temperature", "zone_air_temperature", "heating_valve_position_command"],
        "Fan on and heating valve ≥80%, but discharge air is less than 3 Δ°C above zone temperature.",
        fcu_htg_coil, params=[
            CookbookParam("valve_open", "Valve open threshold", "frac", 0.5, 1.0, 0.05, 0.80),
            CookbookParam("coil_delta", "Minimum heating rise", "°C", 0.555556, 11.111111, 0.277778, 3.0),
            CONFIRM_PARAM()], optional_roles=["supply_fan_operating_status", "supply_fan_command"], confirm_seconds=900),
    CookbookRule("COIL-PERF", "Coil performance (heating and cooling)", "ahu", ["ahu"], [],
        "Coil valve open, opposite valve shut, air temperature change below min_dt.",
        coil_perf, params=[
            CookbookParam("valve_open", "Valve open threshold", "frac", 0.5, 1.0, 0.05, 0.80),
            CookbookParam("valve_shut", "Opposite valve shut", "frac", 0.0, 0.2, 0.01, 0.05),
            CookbookParam("min_dt", "Minimum coil temperature change", "°C", 0.555556, 11.111111, 0.277778, 3.0),
            CONFIRM_PARAM()],
        optional_roles=["heating_valve_position_command", "terminal_unit_heating_valve_position_command", "cooling_valve_position_command", "heating_coil_inlet_air_temperature",
                        "heating_coil_outlet_air_temperature", "cooling_coil_inlet_air_temperature", "cooling_coil_outlet_air_temperature",
                        "mixed_air_temperature", "discharge_air_temperature", "terminal_unit_inlet_air_temperature", "terminal_unit_discharge_air_temperature",
                        "zone_air_temperature", "discharge_air_volume_flow_rate", "supply_fan_operating_status", "supply_fan_command"], confirm_seconds=900),
    CookbookRule("XS-MIX", "Mixing envelope breach", "sensor", ["ahu"],
        ["mixed_air_temperature", "outdoor_air_intake_temperature", "return_air_temperature"],
        "MAT outside OAT/RAT ± band, fan on.",
        __import__("open_fdd.rules.cross_sensor", fromlist=["xs_mix"]).xs_mix, params=[
            CookbookParam("mix_band", "Mixing envelope band", "Δ°C", 0.277778, 5.555556, 0.138889, 1.111111, direction="fewer"),
            CONFIRM_PARAM(15.0)],
        optional_roles=["supply_fan_operating_status", "supply_fan_command"], confirm_seconds=900),
    CookbookRule("XS-COPY", "Copied signal", "sensor", ["ahu", "vav", "zone_other"], [],
        "Pair within copy_tol while moving.",
        __import__("open_fdd.rules.cross_sensor", fromlist=["xs_copy"]).xs_copy, params=[
            CookbookParam("copy_tol", "Copy tolerance", "Δ°C", 0.0, 0.5, 0.01, 0.02, direction="stricter"),
            CookbookParam("change_min", "Minimum change over the run", "Δ°C", 0.277778, 5.555556, 0.138889, 1.0, direction="fewer"),
            CONFIRM_PARAM(120.0, 720.0)],
        optional_roles=["return_air_temperature", "discharge_air_temperature", "mixed_air_temperature", "zone_air_temperature",
                        "terminal_unit_discharge_air_temperature"], confirm_seconds=7200),
    CookbookRule("XS-CLIP", "Clipped sensor", "sensor", ["ahu", "vav", "zone_other"], [],
        "Round maximum held for at least clip_share percent of samples.",
        __import__("open_fdd.rules.cross_sensor", fromlist=["xs_clip"]).xs_clip, params=[
            CookbookParam("clip_share", "Share of samples at the limit", "%", 1.0, 50.0, 1.0, 5.0, direction="fewer"),
            CookbookParam("co2_round", "CO₂ full-scale step", "ppm", 50.0, 1000.0, 50.0, 100.0),
            CookbookParam("static_round", "Duct static full-scale step", "Pa", 5.0, 250.0, 5.0, 25.0),
            CookbookParam("flow_round", "Airflow full-scale step", "L/s", 5.0, 500.0, 5.0, 50.0),
            CONFIRM_PARAM(0.0)],
        optional_roles=["zone_air_co2", "discharge_air_static_pressure", "discharge_air_volume_flow_rate", "supply_fan_operating_status", "supply_fan_command"], confirm_seconds=0),
    CookbookRule("FCU-CLG-COIL", "FCU cooling coil under-delivery", "fcu", ["zone_other", "general", "ahu"],
        ["discharge_air_temperature", "zone_air_temperature", "cooling_valve_position_command", "heating_valve_position_command"],
        "Fan on, cooling valve ≥80%, and heating shut, but discharge air is not below zone temperature.",
        fcu_clg_coil, params=[
            CookbookParam("valve_open", "Valve open threshold", "frac", 0.5, 1.0, 0.05, 0.80),
            CONFIRM_PARAM()], optional_roles=["supply_fan_operating_status", "supply_fan_command"], confirm_seconds=900),
    CookbookRule("FCU-VALVE-PASS-HTG", "FCU heating valve passing", "fcu", ["zone_other", "general", "ahu"],
        ["discharge_air_temperature", "zone_air_temperature", "heating_valve_position_command", "cooling_valve_position_command"],
        "Fan on and both valves shut, but discharge air exceeds zone temperature by more than 3 Δ°C.",
        fcu_valve_pass_htg, params=[
            CookbookParam("pass_delta", "Passing temperature rise", "°C", 0.555556, 11.111111, 0.277778, 3.0),
            CONFIRM_PARAM()], optional_roles=["supply_fan_operating_status", "supply_fan_command"], confirm_seconds=900),
    CookbookRule("FCU-VALVE-PASS-CLG", "FCU cooling valve passing", "fcu", ["zone_other", "general", "ahu"],
        ["discharge_air_temperature", "zone_air_temperature", "heating_valve_position_command", "cooling_valve_position_command"],
        "Fan on and both valves shut, but zone temperature exceeds discharge air by more than 3 Δ°C.",
        fcu_valve_pass_clg, params=[
            CookbookParam("pass_delta", "Passing temperature drop", "°C", 0.555556, 11.111111, 0.277778, 3.0),
            CONFIRM_PARAM()], optional_roles=["supply_fan_operating_status", "supply_fan_command"], confirm_seconds=900),
    CookbookRule("FCU-DAMPER-POS", "FCU damper command/position mismatch", "fcu", ["zone_other", "general", "ahu"],
        ["damper_position_command", "damper_position"],
        "Fan on and damper command ≥15%, but feedback is more than 15 percentage points below command.",
        fcu_damper_pos, params=[
            CookbookParam("command_min", "Minimum damper command", "frac", 0.0, 1.0, 0.05, 0.15),
            CookbookParam("position_error", "Position error", "frac", 0.05, 0.5, 0.05, 0.15),
            CONFIRM_PARAM()], optional_roles=["supply_fan_operating_status", "supply_fan_command"], confirm_seconds=900),
    CookbookRule("FCU-CO2-DAMPER", "FCU high CO2 with low outdoor-air command", "fcu", ["zone_other", "general", "ahu"],
        ["zone_air_co2", "damper_position_command"],
        "Fan on and valid CO₂ exceeds 1000 ppm while damper command remains below 10%.",
        fcu_co2_damper, params=[
            CookbookParam("co2_high_ppm", "High CO₂", "ppm", 600, 2000, 50, 1000),
            CookbookParam("damper_low", "Low damper command", "frac", 0.0, 0.5, 0.05, 0.10),
            CONFIRM_PARAM()], optional_roles=["supply_fan_operating_status", "supply_fan_command"], confirm_seconds=900),
    CookbookRule("FCU-DEADBAND", "FCU heat/cool deadband collapse", "fcu", ["zone_other", "general", "ahu"],
        ["zone_cooling_air_temperature_setpoint", "zone_heating_air_temperature_setpoint"],
        "Pass-through cooling setpoint minus heating setpoint is less than 1°C.",
        fcu_deadband, params=[
            CookbookParam("deadband", "Minimum deadband", "°C", 0.0, 5.0, 0.1, 1.0),
            CONFIRM_PARAM()], confirm_seconds=0),
    CookbookRule("FCU-MODE-CYCLE", "FCU heating/cooling mode cycling", "fcu", ["zone_other", "general", "ahu"],
        ["heating_valve_position_command", "cooling_valve_position_command"],
        "At least four heating/cooling valve mode changes occur in the analysis window.",
        fcu_mode_cycle, params=[
            CookbookParam("mode_valve_min", "Active valve threshold", "frac", 0.0, 0.5, 0.05, 0.10),
            CookbookParam("mode_changes", "Mode changes", "count", 1, 20, 1, 4),
            CONFIRM_PARAM()], confirm_seconds=0),

    # --- VAV zones ---
    CookbookRule("VAV-1", "Zone comfort band", "vav", ["vav", "zone_other", "heatpump", "baseboard"],
        ["zone_air_temperature"],
        "Zone temp outside zone_lo–zone_hi (default 21.1–23.9 °C) during occupied hours when an "
        "occupancy column or Overview calendar is set (require_occupied, default on). "
        "Unoccupied setback stays on VAV-2.",
        vav1, params=[
            CookbookParam("zone_lo", "Zone low", "°C", 12.777778, 22.222222, 0.5, 21.111111),
            CookbookParam("zone_hi", "Zone high", "°C", 22.222222, 29.444444, 0.5, 23.888889),
            CookbookParam("require_occupied", "Require occupied", "bool", 0.0, 1.0, 1.0, 1.0),
            CONFIRM_PARAM()],
        optional_roles=["occupancy_status"], confirm_seconds=900),
    CookbookRule("VAV-2", "Night setback miss", "vav", ["vav", "zone_other", "heatpump", "baseboard"],
        ["zone_air_temperature", "occupancy_status"],
        "Unoccupied AND zone temp > setback_hi (default 20 °C) — heating setback not taken.",
        vav2, params=[
            CookbookParam("setback_hi", "Setback high", "°C", 12.777778, 22.222222, 0.277778, 20.0),
            CONFIRM_PARAM()],
        optional_roles=["occupancy_status"], confirm_seconds=900),
    CookbookRule("VAV-3", "Excessive reheat during warm weather", "vav", ["vav"],
        ["outdoor_air_intake_temperature", "terminal_unit_heating_valve_position_command"], "Air flowing AND OAT > 25.6 °C AND reheat valve > 52%.",
        vav3, params=[
            CookbookParam("reheat_oat", "Warm OAT", "°C", 18.333333, 32.222222, 0.555556, 25.555556),
            CookbookParam("reheat_pct", "Reheat frac", "frac", 0.1, 1.0, 0.02, 0.52),
            CookbookParam("flow_on_min", "Airflow-on min", "L/s", 0.0, 94.3894, 2.359735, 11.798675),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("VAV-4", "Damper stuck at full open", "vav", ["vav"],
        ["damper_position"], "Air flowing AND damper > 97.5% sustained across the window.",
        vav4, params=[
            CookbookParam("full_open_pct", "Full open frac", "frac", 0.8, 1.0, 0.005, 0.975),
            CookbookParam("sustain_hours", "Sustain window", "h", 0.5, 6.0, 0.5, 1.5),
            CookbookParam("flow_on_min", "Airflow-on min", "L/s", 0.0, 94.3894, 2.359735, 11.798675),
            CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("VAV-5", "Airflow sensor bias", "vav", ["vav"],
        ["discharge_air_volume_flow_rate", "damper_position"], "Airflow > ~24 L/s while damper < 10% (implausible flow).",
        vav5, params=[CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("VAV-6", "Reheat when cooling available", "vav", ["vav"],
        ["outdoor_air_intake_temperature", "terminal_unit_heating_valve_position_command"],
        "OAT < 18.3 °C AND reheat valve > 25% (optional cooling-available must be true when mapped).",
        vav6, params=[
            CookbookParam("free_cool_oat", "Free-cool OAT", "°C", 7.222222, 23.888889, 0.555556, 18.333333),
            CookbookParam("reheat_pct", "Reheat frac", "frac", 0.05, 1.0, 0.05, 0.25),
            CONFIRM_PARAM()],
        optional_roles=["cooling_operating_mode_status"], confirm_seconds=900),
    CookbookRule("VAV-REHEAT", "Reheat valve stuck / no temp rise", "vav", ["vav"],
        ["terminal_unit_heating_valve_position_command", "terminal_unit_discharge_air_temperature", "terminal_unit_inlet_air_temperature"],
        "Air flowing AND reheat valve > 30% AND box discharge temp rises < 1.7 °C above duct inlet "
        "(air from AHU) — stuck or failed reheat valve/coil.",
        vav_reheat_stuck, params=[
            CookbookParam("reheat_cmd", "Reheat open frac", "frac", 0.1, 1.0, 0.05, 0.30),
            CookbookParam("min_rise", "Min temp rise", "°C", 0.277778, 8.333333, 0.277778, 1.666667),
            CookbookParam("flow_on_min", "Airflow-on min", "L/s", 0.0, 94.3894, 2.359735, 11.798675),
            CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule(
        "VAV-AHU-LEAVE",
        "VAV leave vs parent AHU SAT (fedBy)",
        "vav",
        ["vav"],
        ["terminal_unit_discharge_air_temperature", "air_handling_unit_discharge_air_temperature"],
        "Air flowing AND |VAV discharge − parent AHU SAT| > band. "
        "Needs package topology (vav_to_ahu) so air_handling_unit_discharge_air_temperature is enriched from the fedBy AHU; "
        "otherwise SKIPPED_MISSING_ROLES. Flags broken reheat, bad sensors, or rogue zones.",
        vav_vs_ahu_leave,
        params=[
            CookbookParam("delta", "Leave Δ vs AHU SAT", "°C", 1.111111, 13.888889, 0.277778, 4.444444),
            CookbookParam("flow_on_min", "Airflow-on min", "L/s", 0.0, 94.3894, 2.359735, 11.798675),
            CONFIRM_PARAM(),
        ],
        confirm_seconds=900,
    ),
    CookbookRule("VAV-7", "Min airflow / fixed high flow", "vav", ["vav"],
        ["discharge_air_volume_flow_rate"],
        "Flow below min SP (when mapped), OR airflow stays flat (low rolling std) at a high mean while air is on "
        "(mins too high / box never modulates), OR discharge_air_volume_flow_rate_minimum itself is excessively high.",
        vav7, params=[
            CookbookParam("flow_on_min", "Airflow-on min", "L/s", 0.0, 94.3894, 2.359735, 11.798675),
            CookbookParam("fixed_flow_max_std", "Fixed-flow max std", "L/s", 0.471947, 37.75576, 0.471947, 7.079205),
            CookbookParam("fixed_flow_min_mean", "Fixed-flow min mean", "L/s", 23.59735, 943.894, 4.71947, 94.3894, direction="fewer"),
            CookbookParam("high_min_flow_sp", "High min-flow SP", "L/s", 23.59735, 943.894, 4.71947, 117.98675, direction="fewer"),
            CONFIRM_PARAM()], confirm_seconds=900),

    # --- Central plants ---
    CookbookRule("CHW-1", "Low chilled-water ΔT", "plant", ["chiller"],
        ["supply_chilled_water_temperature", "return_chilled_water_temperature"], "Pump on AND (CHWR − CHWS) < 2.2 Δ°C.",
        chw1, params=[CookbookParam("min_dt", "Min ΔT", "°C", 0.555556, 6.666667, 0.277778, 2.222222), CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("CHW-2", "DP below SP at max pump speed", "plant", ["chiller"],
        ["chilled_water_pressure_delta", "chilled_water_pressure_delta_setpoint", "chilled_water_pump_command"], "Pump ≥ 87% AND CHW DP < DP SP − 2.2.",
        chw2, params=[
            CookbookParam("dp_margin", "DP margin", "Pa", 3447.379, 41368.542, 689.476, 15168.465),
            CookbookParam("pump_hi", "Pump high-speed threshold", "frac", 0.5, 1.0, 0.01, 0.87),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("CHW-3", "Plant supply temp outside deadband", "plant", ["chiller"],
        ["supply_chilled_water_temperature", "supply_chilled_water_temperature_setpoint", "chilled_water_pump_command"], "Pump on AND |CHWS − CHWS SP| > 1.2 Δ°C.",
        chw3, params=[CookbookParam("sp_band", "SP band", "°C", 0.277778, 3.333333, 0.055556, 1.222222), CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("CHW-4", "Flow high at max pump", "plant", ["chiller"],
        ["chilled_water_volume_flow_rate", "chilled_water_pump_command"], "Pump ≥ 87% AND CHW flow > 69.4 L/s.",
        chw4, params=[
            CookbookParam("flow_hi", "Flow high", "L/s", 12.61804, 189.2706, 3.15451, 69.39922),
            CookbookParam("pump_hi", "Pump high-speed threshold", "frac", 0.5, 1.0, 0.01, 0.87),
            CONFIRM_PARAM()], confirm_seconds=300),

    # --- Heat pumps ---
    CookbookRule("HP-1", "Discharge cold when heating", "heatpump", ["heatpump"],
        ["discharge_air_temperature", "zone_air_temperature", "supply_fan_command"], "Fan on, zone < 20.6 °C, discharge SAT < 29.4 °C.",
        hp1, params=[
            CookbookParam("min_sat", "Min heating SAT", "°C", 21.111111, 43.333333, 0.555556, 29.444444, direction="stricter"),
            CookbookParam("zone_cold", "Zone cold", "°C", 15.555556, 22.222222, 0.277778, 20.555556, direction="stricter"),
            CONFIRM_PARAM()], confirm_seconds=600),

    # --- Weather / condenser ---
    CookbookRule("WX-1", "OA temperature spike", "weather", ["weather"],
        ["outdoor_air_intake_temperature"], "OAT sample-to-sample jump > 8.9 Δ°C.",
        wx1, params=[CookbookParam("spike_limit", "Spike limit", "°C", 2.222222, 22.222222, 0.555556, 8.888889), CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("CW-OPT-1", "Condenser water not optimized vs wet-bulb", "plant", ["chiller", "cooling_tower"],
        ["supply_condenser_water_temperature"],
        "CW supply significantly colder than web wet-bulb + design approach (Stull WB) — tower over-cooling / not optimized.",
        cw_opt, params=[
            CookbookParam("cw_approach", "Design approach", "°C", 1.666667, 8.333333, 0.277778, 3.888889, direction="stricter"),
            CookbookParam("cw_slack", "Slack below target", "°C", 0.277778, 3.333333, 0.277778, 1.111111, direction="fewer"),
            CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule(
        "CW-APR-1",
        "High CW approach at full tower fan",
        "plant",
        ["chiller", "cooling_tower"],
        ["supply_condenser_water_temperature"],
        "At full tower fan speed, leaving CW − web wet-bulb exceeds approach_max (default 4.44°C, typically 2.8–5.6°C). "
        "Suspect OA→wet-bulb / CW sensor mismatch or cooling-tower performance degradation.",
        cw_apr,
        params=[
            CookbookParam("approach_max", "Max approach at full fan", "°C", 2.777778, 8.333333, 0.277778, 4.444444),
            CookbookParam("tower_fan_hi", "Tower fan full-speed threshold", "frac", 0.8, 1.0, 0.01, 0.95),
            CONFIRM_PARAM(),
        ],
        optional_roles=["cooling_tower_fan_command", "cooling_tower_fan_command", "supply_fan_command", "weather_service_air_wet_bulb_temperature"],
        confirm_seconds=900,
    ),
    CookbookRule(
        "CW-FAN-1",
        "Excess tower fan energy vs wet-bulb limit",
        "plant",
        ["chiller", "cooling_tower"],
        ["supply_condenser_water_temperature"],
        "Tower fans at full speed while leaving CW is well above web wet-bulb + design approach "
        "(approach + excess_beyond). Fans are chasing a CW temp that is theoretically hard/impossible — excess fan energy.",
        cw_fan_excess,
        params=[
            CookbookParam("cw_approach", "Design approach", "°C", 1.666667, 8.333333, 0.277778, 3.888889),
            CookbookParam("excess_beyond_approach", "Excess beyond approach", "°C", 1.111111, 11.111111, 0.277778, 2.777778),
            CookbookParam("tower_fan_hi", "Tower fan full-speed threshold", "frac", 0.8, 1.0, 0.01, 0.95),
            CONFIRM_PARAM(),
        ],
        optional_roles=["cooling_tower_fan_command", "cooling_tower_fan_command", "supply_fan_command", "weather_service_air_wet_bulb_temperature"],
        confirm_seconds=900,
    ),

    # --- Trim & respond advisory (lumped with AHU / plants) ---
    CookbookRule("TRIM-1", "Duct static trim advisory", "trim", ["ahu"],
        ["discharge_air_static_pressure", "discharge_air_static_pressure_reset_request_count"], "Duct static high (> 336 Pa) while VAV pressure requests are low.",
        trim1, params=[
            CookbookParam("duct_hi", "Duct static high", "Pa", 124.42, 746.52, 12.442, 335.934, direction="fewer"),
            CookbookParam("request_lo", "Request sum low", "count", 0.0, 10.0, 0.5, 1.0, direction="stricter"),
            CONFIRM_PARAM()], confirm_seconds=1800),
    CookbookRule("TRIM-3", "HWST trim advisory", "trim", ["boiler"],
        ["supply_hot_water_temperature", "hot_water_reset_request_count"], "HW supply > 71.1 °C while the reset request sum is at or below request_lo.",
        trim3, params=[
            CookbookParam("hwst_hi", "HWST high", "°C", 48.888889, 93.333333, 0.555556, 71.111111, direction="fewer"),
            CookbookParam("request_lo", "Request sum low", "count", 0.0, 10.0, 0.5, 1.0, direction="stricter"),
            CONFIRM_PARAM()], confirm_seconds=1800),
    CookbookRule("TRIM-4", "CHW plant reset advisory", "trim", ["chiller"],
        ["supply_chilled_water_temperature", "chilled_water_reset_request_count"], "CHW supply < 7.2 °C while the reset request sum is at or below request_lo.",
        trim4, params=[
            CookbookParam("chw_lo", "CHWS low", "°C", 1.666667, 12.777778, 0.277778, 7.222222, direction="stricter"),
            CookbookParam("request_lo", "Request sum low", "count", 0.0, 10.0, 0.5, 1.0, direction="stricter"),
            CONFIRM_PARAM()], confirm_seconds=1800),
    CookbookRule("SHORT-CYCLE", "Short cycling", "plant", ["boiler", "chiller", "heatpump", "ahu"], [],
        "Too many starts per hour, or short on-times.",
        short_cycle, params=[
            CookbookParam("max_starts_per_hour", "Max starts per hour", "count", 2.0, 20.0, 1.0, 6.0, direction="fewer"),
            CookbookParam("min_on_seconds", "Minimum on-time", "sec", 60.0, 1800.0, 60.0, 600.0, direction="stricter"),
            CookbookParam("min_short_cycles", "Short cycles per hour", "count", 1.0, 10.0, 1.0, 3.0, direction="fewer"),
            CONFIRM_PARAM(0.0)],
        optional_roles=["boiler_operating_status", "compressor_operating_status", "chiller_operating_status", "chiller_electric_current", "chiller_electric_power"],
        confirm_seconds=0),

    # --- Extended families ---
    CookbookRule(
        "SCHED-1",
        "Unoccupied runtime",
        "schedule",
        ["ahu"],
        ["occupancy_status", "supply_fan_operating_status"],
        "Fan running while occupancy is unoccupied (Overview calendar → occupancy_status). "
        "When zone_air_temperature is mapped, also require zone inside comfort_low…comfort_high "
        "(defaults 21.1–23.9 °C; synced from Overview zone band).",
        sched1,
        params=[
            CookbookParam("comfort_low", "Comfort low", "°C", 10.0, 26.666667, 0.277778, 21.111111),
            CookbookParam("comfort_high", "Comfort high", "°C", 12.777778, 32.222222, 0.277778, 23.888889),
            CONFIRM_PARAM(),
        ],
        optional_roles=["zone_air_temperature"],
        confirm_seconds=1800,
    ),
    CookbookRule(
        "SCHED-247",
        "Always-on fan or pump runtime",
        "schedule",
        ["ahu", "vav", "chiller", "boiler", "heatpump"],
        [],
        "Ranked proof (status/current > command) is on for ≥ always_on_pct of the window. "
        "Pressure is inferred runtime only and does not trip this rule ID.",
        _sched247,
        params=[
            CookbookParam("always_on_pct", "Always-on fraction", "frac", 0.80, 1.0, 0.01, 0.95, direction="fewer"),
            CookbookParam(
                "pressure_on_min", "Pressure-on evidence", "Pa", 12.442, 497.68, 12.442, 49.768,
                direction="stricter",
            ),
            CONFIRM_PARAM(),
        ],
        optional_roles=[
            "supply_fan_operating_status",
            "pump_operating_status",
            "chilled_water_pump_operating_status",
            "chiller_operating_status",
            "compressor_operating_status",
            "cooling_tower_fan_command",
            "cooling_tower_fan_command",
            "supply_fan_command",
            "chilled_water_pump_command",
            "discharge_air_static_pressure",
            "chilled_water_pressure_delta",
        ],
        confirm_seconds=3600,
    ),
    CookbookRule("RESET-1", "SAT reset not tracking outdoor air", "ahu", ["ahu"],
        ["discharge_air_temperature_setpoint", "outdoor_air_intake_temperature"],
        "Fan on AND |SAT SP − (11.1 + 0.25×(OAT−18.3))| > 1.7 Δ°C.",
        reset1, params=[
            CookbookParam("reset_err", "Reset error", "Δ°C", 0.277778, 5.555556, 0.277778, 1.666667),
            CookbookParam("reset_sat_at_ref", "SAT SP at the reset OAT reference", "°C", 7.222222, 18.333333, 0.277778, 11.111111),
            CookbookParam("reset_slope", "Reset slope", "Δ°C/Δ°C", 0.05, 1.0, 0.05, 0.25),
            CookbookParam("reset_oat_ref", "Reset OAT ref", "°C", 10.0, 26.666667, 0.555556, 18.333333),
            CONFIRM_PARAM()],
        optional_roles=["supply_fan_operating_status", "supply_fan_command"], confirm_seconds=900),
    CookbookRule("CMD-1", "Fan cmd/status mismatch", "ahu", ["ahu"],
        ["supply_fan_command", "supply_fan_operating_status"], "Fan command and proven status disagree.",
        cmd1, params=[CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("OA-1", "Low OA fraction", "ahu", ["ahu"],
        ["mixed_air_temperature", "return_air_temperature", "outdoor_air_intake_temperature", "supply_fan_operating_status"], "Estimated OA fraction < 15% with adequate OAT/RAT split.",
        oa1, params=[
            CookbookParam("min_oa_frac", "Min OA fraction", "frac", 0.05, 0.4, 0.01, 0.15, direction="stricter"),
            CookbookParam("oat_rat_guard", "Min |RAT−OAT| guard", "Δ°C", 0.277778, 3.333333, 0.055556, 1.222222, direction="fewer"),
            CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("DMP-1", "OA damper leakage", "ahu", ["ahu"],
        ["outdoor_air_intake_temperature", "mixed_air_temperature", "outdoor_air_intake_damper_position_command"], "Damper ≤ 5% but MAT tracks OAT within 1.1 Δ°C — leaking OA damper.",
        dmp1, params=[CookbookParam("leak_delta", "Leak ΔT", "Δ°C", 0.277778, 3.333333, 0.277778, 1.111111), CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule(
        "VLV-1",
        "Cooling valve leakage",
        "ahu",
        ["ahu"],
        ["discharge_air_temperature", "discharge_air_temperature_setpoint", "cooling_valve_position_command"],
        "Cooling valve ≤ 5% AND (SAT < discharge_air_temperature_setpoint − sat_err OR SAT < MAT − mat_leak_delta). "
        "Fan proven on when supply_fan_operating_status/supply_fan_command present (operational gate).",
        vlv1,
        params=[
            CookbookParam("sat_err", "SAT vs SP leak ΔT", "Δ°C", 0.277778, 4.444444, 0.277778, 1.111111),
            CookbookParam("mat_leak_delta", "SAT vs MAT leak ΔT", "Δ°C", 0.277778, 6.666667, 0.277778, 1.111111),
            CONFIRM_PARAM(),
        ],
        optional_roles=["mixed_air_temperature", "supply_fan_operating_status", "supply_fan_command"],
        confirm_seconds=900,
    ),
]

# Curated one-sentence summaries (explicit field — UI/DOCX/MD must not fall back to equation).
RULE_SUMMARY_OVERRIDES: dict[str, str] = {
    "SV-RANGE": "Flags any modeled sensor reading outside its physical hard range.",
    "SV-FLATLINE": "Flags a sensor that stays stuck within a tiny band for too long.",
    "SV-SPIKE": "Flags an implausible sample-to-sample jump for the sensor type.",
    "SV-STALE": "Flags a sensor that sent no valid sample for longer than the stale threshold — missing data.",
    "SV-RATE": "Flags implausible sustained sensor rates of change using location- and state-aware thresholds.",
    "XS-MIX": "Flags mixed air outside the outdoor/return envelope: a sensor or mapping fault.",
    "XS-COPY": "Flags two temperature roles carrying one copied, changing signal.",
    "XS-CLIP": "Flags a sensor piled up at a round transmitter full scale.",
    "PID-HUNT-1": "Flags control outputs that oscillate enough to suggest loop hunting.",
    "SCHED-247": "Flags fans or pumps that stay on for nearly the entire analysis window (24/7 runtime).",
    "ECON-3": "Flags mechanical cooling during web free-cool weather when the OA damper is not fully integrated.",
    "ECON-6": "Flags an AHU economizing above min-OA when web outdoor air is below freezing (−3.9 °C).",
    "ECON-7": "Flags cooling demand during economizer-OK web weather (dew point < 15.6 °C, dry-bulb < 22.2 °C) while the OA damper is not economizing.",
    "MECH-OAT-1": "Flags proven DX or chiller cooling while web dry-bulb is below 15.6 °C.",
    "HW-OAT-1": "Flags a boiler, hot-water plant or hot-water pump proven on while web dry-bulb is above 18.3 °C.",
    "CHW-NOLOAD-1": "Flags a chiller running while mapped zones or AHU SAT show the building is satisfied.",
    "FC1": "Flags duct static too low while the supply fan is near full speed.",
    "FC2": "Flags mixed-air temperature colder than the OAT/RAT mixing envelope allows.",
    "FC3": "Flags mixed-air temperature warmer than the OAT/RAT mixing envelope allows.",
    "VAV-1": "Flags occupied-band zone temperature violations.",
    "VAV-2": "Flags unoccupied zones that never drop into heating setback.",
    "VAV-6": "Flags reheat while outdoor air is cool enough for free cooling.",
    "RESET-1": "Flags SAT setpoint that is not tracking the outdoor-air reset curve.",
    "VAV-REHEAT": "Flags reheat commanded open with airflow but almost no discharge temperature rise.",
    "VAV-AHU-LEAVE": "Flags VAV discharge far from the parent AHU SAT when topology feeds are known.",
    "OAT-METEO": "Flags large disagreement between BAS outdoor-air temp and web weather OAT.",
    "SCHED-1": "Flags fan runtime during unoccupied hours from the Overview calendar.",
    "VLV-1": "Flags a closed cooling valve while SAT still looks like valve leakage.",
    "CW-OPT-1": "Flags condenser water colder than wet-bulb + approach — tower over-cooling / not optimized.",
    "CW-APR-1": "Flags high CW–wet-bulb approach at full tower fan — sensor mismatch or tower degradation.",
    "CW-FAN-1": "Flags full-speed tower fans while CW is well above theoretical WB+approach — excess fan energy.",
}


def _one_sentence_from_equation(equation: str, title: str) -> str:
    text = (equation or "").strip()
    if not text:
        return f"{title}."
    # First sentence; keep engineer-facing prose distinct from multi-clause equations.
    part = text.split(". ")[0].strip()
    if not part.endswith("."):
        part += "."
    return part


def _ensure_rule_summaries() -> None:
    for r in RULES:
        override = RULE_SUMMARY_OVERRIDES.get(r.id)
        if override:
            r.summary = override
        elif not (r.summary or "").strip():
            r.summary = _one_sentence_from_equation(r.equation, r.title)


def _ensure_confirm_param_defaults() -> None:
    """Slider default for confirm_min must equal rule.confirm_seconds / 60.

    Without this, CONFIRM_PARAM()'s hard-coded 5.0 silently overrode every
    declared confirm window via ``_confirm_seconds`` (params always include the key).
    """
    for r in RULES:
        target = round(float(r.confirm_seconds) / 60.0, 6)
        for p in r.params:
            if p.key == "confirm_min":
                p.default = target
                if p.max < target:
                    p.max = target
                if not p.direction:
                    p.direction = "fewer"
                break
        else:
            r.params.append(CONFIRM_PARAM(target))


_ensure_rule_summaries()
_ensure_confirm_param_defaults()

RULES_BY_ID: dict[str, CookbookRule] = {r.id: r for r in RULES}
# Compatibility alias (same compute as SV-RATE)
RULES_BY_ID["SV-SLEW"] = RULES_BY_ID["SV-RATE"]


def rules_for_kind(kind: str) -> list[CookbookRule]:
    return [r for r in RULES if kind in r.equipment_kinds]


def catalog() -> list[dict]:
    return [r.to_dict() for r in RULES]
