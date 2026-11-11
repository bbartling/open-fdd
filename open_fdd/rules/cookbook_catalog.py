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
    sweep_assessable_role,
)

# ---------------------------------------------------------------------------
# Shared helpers (mirror cookbook "Setup & shared helpers")
# ---------------------------------------------------------------------------


def norm_cmd(
    s: pd.Series | None,
    *,
    representation: str = "fraction",
) -> pd.Series:
    """Command/position as a fraction 0–1 (issue #1541: one declared scale per column).

    The input contract (sql/fdd/role_scales.json) says every command/position role arrives as a fraction 0–1,
    so the default is a plain numeric pass-through: there is NO magnitude guess (a stored 1 is 100 %, a 0.01 is
    1 %). Pass ``representation='percent'`` only for a source that is explicitly declared 0–100; ``auto`` (a
    series-level magnitude guess) is not offered by the rules any more.
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
    for role in ("duct-static-pressure", "chw-diff-pressure", "hw-diff-pressure"):
        if role not in d.columns or not d[role].notna().any():
            continue
        s = pd.to_numeric(d[role], errors="coerce")
        return (s.notna() & (s.abs() > thr)).reindex(d.index).fillna(False)
    return None


def _sched247_role_mask(d: pd.DataFrame, roles: tuple[str, ...], *, command: bool) -> tuple[pd.Series | None, str | None]:
    for role in roles:
        if role not in d.columns or not d[role].notna().any():
            continue
        if command:
            mask = norm_cmd(d[role]).fillna(0) > SCHED247_CMD_ON_FRAC
        else:
            mask = as_bool(d[role])
        return mask.reindex(d.index).fillna(False).astype(bool), role
    return None, None


def _sched247(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Always-on runtime using ranked proof (status/current > command).

    Pressure is inferred evidence only — it does not OR into the FAULT mask
    (4.3 migration). Structured proof fields are stored on ``d.attrs``.
    """
    from open_fdd.rules.base import hours_true

    thr = _f(p, "always_on_pct", 0.95)
    status, status_role = _sched247_role_mask(
        d,
        (
            "fan-status",
            "pump-status",
            "chw-pump-status",
            "hw-pump-status",
            "chiller-status",
            "compressor-status",
            "fan-current",
            "pump-current",
            "chiller-current",
        ),
        command=False,
    )
    command, command_role = _sched247_role_mask(
        d,
        ("tower-fan-cmd", "cw-fan-cmd", "fan-cmd", "chw-pump-cmd", "hw-pump-cmd"),
        command=True,
    )
    inferred = _pressure_on_mask(d, p)
    if inferred is not None:
        inferred = inferred.reindex(d.index).fillna(False).astype(bool)

    if status is not None:
        proven = status
        proof_source = status_role or "status"
        proof_confidence = 0.7 if (status_role or "").endswith("-current") else 1.0
    elif command is not None:
        proven = command
        proof_source = f"{command_role} (cmd)"
        proof_confidence = 0.5
    else:
        proven = _false(d.index)
        proof_source = "none"
        proof_confidence = 0.0

    conflict = _false(d.index)
    if status is not None and command is not None:
        conflict = status.astype(bool) != command.astype(bool)

    proven_h = hours_true(proven, poll)
    inferred_h = hours_true(inferred, poll) if inferred is not None else 0.0
    conflict_h = hours_true(conflict, poll)
    d.attrs["sched247_proof"] = {
        "proof_source": proof_source,
        "proof_confidence": proof_confidence,
        "proven_runtime_hours": round(float(proven_h), 3),
        "inferred_runtime_hours": round(float(inferred_h), 3),
        "conflicting_signal_hours": round(float(conflict_h), 3),
    }

    frac = float(proven.mean()) if len(proven) else 0.0
    if proof_source != "none" and frac >= thr:
        return proven.reindex(d.index).fillna(False)
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
        ("fan-status", 0.05),
        ("fan-cmd", 0.01),
        ("zone-airflow", 23.597350),
        ("pump-status", 0.05),
        ("chw-pump-cmd", 0.05),
        ("chiller-status", 0.05),
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


def _sweep_segments(d: pd.DataFrame, masks: dict[str, pd.Series], poll: float, p: dict) -> dict[str, list[dict]]:
    max_silence = _f(p, "max_silence_hours", 0.5)
    return {
        role: _elapsed_segments(d, pd.to_numeric(d[role], errors="coerce"), mask,
                                poll=poll, max_silence_hours=max_silence)
        for role, mask in masks.items() if role in d.columns
    }


def _publish_elapsed_sweep(d: pd.DataFrame, masks: dict[str, pd.Series], *, poll: float, p: dict, rule_tag: str) -> pd.Series:
    segments = _sweep_segments(d, masks, poll, p)
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
    "outside-air-damper",
    "cooling-valve",
    "heating-valve",
    "damper",
    "reheat-valve",
    "fan-cmd",
    "return-fan-cmd",
    "chw-pump-cmd",
    "hw-pump-cmd",
    "cw-pump-cmd",
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
    energized = _flatline_energized(d)
    limits = _sweep_limits(d)
    for role in SWEEP_SENSOR_ROLES:
        if role not in d.columns:
            continue
        if not sweep_assessable_role(role, None, units_map, rule_id="SV-RANGE", limits=limits):
            continue
        s = pd.to_numeric(d[role], errors="coerce")
        if not s.notna().any():
            continue
        lim = limits_for_haystack_role(role, limits)
        if lim is None:
            raise ValueError(f"SV-RANGE role {role!r} has no SI limit")
        base_lo, base_hi = lim["lo"], lim["hi"]
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
    from open_fdd.rules.sensor_sweep_catalog import flatline_tolerance_for_role

    tol = _f(p, "flatline_tol", 0.055556)
    hours = _f(p, "flatline_hours", 1.0)
    max_silence = _f(p, "max_silence_hours", 0.5)
    # SV-FLATLINE SQL always requires an energized proof for ordinary samples;
    # preserve the legacy pandas-only knob in the catalog, but do not let it
    # diverge from SQL. Silence intervals are still accounted independently.
    gate = _flatline_energized(d)
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
        role_gate = gate
        if role_gate is not None:
            role_gate = role_gate.reindex(s.index).fillna(False)
        role_mask = _window_flatline_mask(
            s,
            hours=hours,
            tolerance=flatline_tolerance_for_role(role, tol, limits),
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
    require_gate = _f(p, "require_operational_gate", 1.0) >= 0.5
    energized = _flatline_energized(d)
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
        lim = limits_for_haystack_role(role, limits)
        if lim is None:
            raise ValueError(f"SV-SPIKE role {role!r} has no SI limit")
        limit = lim["spike"] * type_scale
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
    """Measure stable periods and long silent tails independently per sensor."""
    hours = _f(p, "stale_hours", 2.0)
    tolerance = _f(p, "stale_tol", 0.027778)
    max_silence = _f(p, "max_silence_hours", 0.5)
    units_map = _units_map(d)
    limits = _sweep_limits(d)
    present = [
        r
        for r in FLATLINE_SENSOR_ROLES
        if r in d.columns and sweep_assessable_role(r, None, units_map, rule_id="SV-STALE", limits=limits)
    ]
    per_role: dict[str, pd.Series] = {}
    for role in present:
        s = pd.to_numeric(d[role], errors="coerce")
        if not s.notna().any():
            continue
        role_tol = stale_tolerance_for_role(role, tolerance, limits)
        per_role[role] = _window_flatline_mask(
            s,
            hours=hours,
            tolerance=role_tol,
            max_silence_hours=max_silence,
            poll=poll,
        )
    return _publish_elapsed_sweep(d, per_role, poll=poll, p=p, rule_tag="SV-STALE")


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
    enable_col = "loop-enabled" if "loop-enabled" in d.columns else None
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
    # Match production SQL (fan_status then fan_cmd) — Wave J / #875.
    if "fan-status" in d.columns:
        return as_bool(d["fan-status"]).astype(float)
    if "fan-cmd" in d.columns:
        return norm_cmd(d["fan-cmd"]).fillna(0)
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
    fan = _fan(d)
    raw = (
        d["duct-static-pressure"].notna() & d["duct-static-pressure-sp"].notna()
        & (d["duct-static-pressure"] < d["duct-static-pressure-sp"] - err)
        & (fan >= fan_hi)
    )
    return raw.fillna(False) & _fc1_mode_stable(d, p, poll)


def fc2(d, p, poll):
    """MAT below OAT/RAT mixing envelope (GL36 B).

    ``mix_tol`` widens the envelope on both sides:
    ``mat + tol < min(rat - tol, oat - tol)`` ≡ ``mat < min(rat, oat) - 2·tol``.
    Never subtract the same tol from both sides of the inequality (that cancels).
    """
    eps_mat = _gl36_value(p, "eps_mat", "mix_tol", MIX_TOL)
    eps_rat = _gl36_value(p, "eps_rat", "mix_tol", MIX_TOL)
    eps_oat = _gl36_value(p, "eps_oat", "mix_tol", MIX_TOL)
    fan_on = _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    fan = _fan(d)
    raw = (
        (fan > fan_on)
        & d["mixed-air-temp"].notna() & d["outside-air-temp"].notna() & d["return-air-temp"].notna()
        & ((d["mixed-air-temp"] + eps_mat) < np.minimum(d["return-air-temp"] - eps_rat, d["outside-air-temp"] - eps_oat))
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
        & d["mixed-air-temp"].notna() & d["outside-air-temp"].notna() & d["return-air-temp"].notna()
        & ((d["mixed-air-temp"] - eps_mat) > np.maximum(d["return-air-temp"] + eps_rat, d["outside-air-temp"] + eps_oat))
    )
    return _gl36_fault(raw, d, p, poll)


def fc4(d, p, poll):
    """PID hunting — operating-state entry transitions per hour."""
    delta_os_max = _f(p, "delta_os_max", 5.0)
    htg = norm_cmd(d["heating-valve"]).fillna(0) if "heating-valve" in d else pd.Series(0.0, index=d.index)
    clg = norm_cmd(d["cooling-valve"]).fillna(0) if "cooling-valve" in d else pd.Series(0.0, index=d.index)
    fan = _fan(d)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0) if "outside-air-damper" in d else pd.Series(0.0, index=d.index)
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
    entries = (modes.eq(1) & modes.shift().ne(1))
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
    htg = norm_cmd(d["heating-valve"]).fillna(0)
    raw = (
        d["discharge-air-temp"].notna() & d["mixed-air-temp"].notna()
        & (fan > fan_on) & (htg > htg_on)
        & ((d["discharge-air-temp"] + eps_sat) <= (d["mixed-air-temp"] - eps_mat + delta_tsf))
    )
    return _gl36_fault(raw, d, p, poll)


def fc6(d, p, poll):
    airflow_err = _gl36_value(p, "eps_airflow", "airflow_err", 0.15)
    oat_rat_min = _gl36_value(p, "delta_t_min", "oat_rat_delta_min", 2.777778)
    design_flow = _f(p, "min_flow_design", 2359.735)
    fan_on = _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    fan = _fan(d)
    rat_minus_oat = (d["return-air-temp"] - d["outside-air-temp"]).abs()
    pct_oa = ((d["mixed-air-temp"] - d["return-air-temp"]) / (d["outside-air-temp"] - d["return-air-temp"]).replace(0, np.nan)).clip(lower=0)
    perc_oamin = design_flow / d["vav-total-airflow"].replace(0, np.nan)
    oa_err = (pct_oa - perc_oamin).abs()
    raw = (
        d["mixed-air-temp"].notna() & d["outside-air-temp"].notna() & d["return-air-temp"].notna() & d["vav-total-airflow"].notna()
        & (rat_minus_oat >= oat_rat_min) & (oa_err > airflow_err) & (fan > fan_on)
    )
    return _gl36_fault(raw, d, p, poll)


def fc7(d, p, poll):
    sat_err = _gl36_value(p, "eps_sat", "sat_err", 0.638889)
    fan_on = _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    htg_full = _f(p, "htg_full_min", 0.9)
    fan = _fan(d)
    htg = norm_cmd(d["heating-valve"]).fillna(0)
    raw = (
        d["discharge-air-temp"].notna() & d["discharge-air-temp-sp"].notna()
        & (fan > fan_on) & (d["discharge-air-temp"] < d["discharge-air-temp-sp"] - sat_err) & (htg >= htg_full)
    )
    return _gl36_fault(raw, d, p, poll)


def fc8(d, p, poll):
    eps_mat = _gl36_value(p, "eps_mat", "mix_tol", MIX_TOL)
    eps_sat = _gl36_value(p, "eps_sat", "supply_tol", SUPPLY_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    econ_min = _f(p, "econ_min_pos", AHU_MIN_OA_DPR)
    clg_inactive = _f(p, "clg_inactive_max", 0.1)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    sat_mat_err = (d["discharge-air-temp"] - delta_tsf - d["mixed-air-temp"]).abs()
    sqrt_tol = float(np.sqrt(eps_sat**2 + eps_mat**2))
    raw = (
        d["discharge-air-temp"].notna() & d["mixed-air-temp"].notna()
        & (econ > econ_min) & (clg < clg_inactive) & (sat_mat_err > sqrt_tol)
    )
    return _gl36_fault(raw, d, p, poll)


def fc9(d, p, poll):
    eps_oat = _gl36_value(p, "eps_oat", "mix_tol", MIX_TOL)
    eps_sat = _gl36_value(p, "eps_sat", "mix_tol", MIX_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    econ_min = _f(p, "econ_min_pos", AHU_MIN_OA_DPR)
    clg_inactive = _f(p, "clg_inactive_max", 0.1)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    raw = (
        d["outside-air-temp"].notna() & d["discharge-air-temp-sp"].notna()
        & (econ > econ_min) & (clg < clg_inactive)
        & ((d["outside-air-temp"] - eps_oat) > (d["discharge-air-temp-sp"] - delta_tsf + eps_sat))
    )
    return _gl36_fault(raw, d, p, poll)


def fc10(d, p, poll):
    eps_mat = _gl36_value(p, "eps_mat", "mix_tol", MIX_TOL)
    eps_oat = _gl36_value(p, "eps_oat", "mix_tol", MIX_TOL)
    econ_full = _f(p, "econ_full_open", 0.9)
    clg_on = _f(p, "clg_on_min", 0.01)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    abs_mat_oat = (d["mixed-air-temp"] - d["outside-air-temp"]).abs()
    sqrt_tol = float(np.sqrt(eps_mat**2 + eps_oat**2))
    raw = d["mixed-air-temp"].notna() & d["outside-air-temp"].notna() & (clg > clg_on) & (econ > econ_full) & (abs_mat_oat > sqrt_tol)
    return _gl36_fault(raw, d, p, poll)


def fc11(d, p, poll):
    eps_oat = _gl36_value(p, "eps_oat", "mix_tol", MIX_TOL)
    eps_sat = _gl36_value(p, "eps_sat", "mix_tol", MIX_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    econ_full = _f(p, "econ_full_open", 0.9)
    clg_on = _f(p, "clg_on_min", 0.01)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    raw = (
        d["outside-air-temp"].notna() & d["discharge-air-temp-sp"].notna() & (clg > clg_on) & (econ > econ_full)
        & ((d["outside-air-temp"] + eps_oat) < (d["discharge-air-temp-sp"] - delta_tsf - eps_sat))
    )
    return _gl36_fault(raw, d, p, poll)


def fc12(d, p, poll):
    eps_mat = _gl36_value(p, "eps_mat", "mix_tol", MIX_TOL)
    eps_sat = _gl36_value(p, "eps_sat", "supply_tol", SUPPLY_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    econ_min = _f(p, "econ_min_pos", AHU_MIN_OA_DPR)
    econ_full = _f(p, "econ_full_open", 0.9)
    clg_on = _f(p, "clg_on_min", 0.01)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    sat_check = d["discharge-air-temp"] - eps_sat - delta_tsf
    mat_check = d["mixed-air-temp"] + eps_mat
    raw = (
        d["discharge-air-temp"].notna() & d["mixed-air-temp"].notna() & (clg > clg_on)
        & (sat_check > mat_check) & ((econ <= econ_min) | (econ > econ_full))
    )
    return _gl36_fault(raw, d, p, poll)


def fc13(d, p, poll):
    sat_err = _gl36_value(p, "eps_sat", "sat_err", 0.638889)
    econ_min = _f(p, "econ_min_pos", AHU_MIN_OA_DPR)
    econ_full = _f(p, "econ_full_open", 0.9)
    clg_full = _f(p, "clg_full_min", 0.01)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    raw = (
        d["discharge-air-temp"].notna() & d["discharge-air-temp-sp"].notna() & (clg >= clg_full)
        & (d["discharge-air-temp"] > d["discharge-air-temp-sp"] + sat_err) & ((econ <= econ_min) | (econ > econ_full))
    )
    return _gl36_fault(raw, d, p, poll)


def fc14(d, p, poll):
    eps_ccet = _gl36_value(p, "eps_ccet", "mix_tol", MIX_TOL)
    eps_cclt = _gl36_value(p, "eps_cclt", "mix_tol", MIX_TOL)
    delta_tsf = _f(p, "delta_supply_fan", DELTA_SUPPLY_FAN)
    econ_min = _f(p, "econ_min_pos", AHU_MIN_OA_DPR)
    clg_inactive = _f(p, "clg_inactive_max", 0.1)
    htg_on = _f(p, "htg_on_min", 0.01)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    htg = norm_cmd(d["heating-valve"]).fillna(0) if "heating-valve" in d else pd.Series(0.0, index=d.index)
    fan = _fan(d)
    delta = d["cooling-coil-entering-temp"] - d["cooling-coil-leaving-temp"]
    tol = float(np.sqrt(eps_ccet**2 + eps_cclt**2)) + delta_tsf
    raw = (
        d["cooling-coil-entering-temp"].notna() & d["cooling-coil-leaving-temp"].notna()
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
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    delta = d["heating-coil-entering-temp"] - d["heating-coil-leaving-temp"]
    tol = float(np.sqrt(eps_hcet**2 + eps_hclt**2)) + delta_tsf
    raw = (
        d["heating-coil-entering-temp"].notna() & d["heating-coil-leaving-temp"].notna()
        & (delta >= tol)
        & (((econ > econ_min) & (clg < clg_inactive)) | ((clg > clg_on) & (econ <= econ_min)) | ((clg > clg_on) & (econ > econ_full)))
    )
    return _gl36_fault(raw, d, p, poll)


def ahu_sat_dev(d, p, poll):
    err = _f(p, "sat_dev_err", 2.777778)
    return d["discharge-air-temp"].notna() & d["discharge-air-temp-sp"].notna() & (d["discharge-air-temp"].sub(d["discharge-air-temp-sp"]).abs() > err)


def ahu_duct_high(d, p, poll):
    """Duct static above SP + margin. Gate (not equation) decides fan-vs-pressure active window."""
    default_margin = 62.21
    margin = _f(p, "duct_high_margin", default_margin)
    return (
        d["duct-static-pressure"].notna()
        & d["duct-static-pressure-sp"].notna()
        & (d["duct-static-pressure"] > d["duct-static-pressure-sp"] + margin)
    )


def ahu_simul_heat_cool(d, p, poll):
    thr = _f(p, "valve_open_pct", 0.10)
    htg = norm_cmd(d["heating-valve"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    return (htg > thr) & (clg > thr)


# ---------------------------------------------------------------------------
# Economizer & ventilation (ECON-1..5) — ECON-3 handled specially in engine
# ---------------------------------------------------------------------------


def econ1(d, p, poll):
    oat_min = _f(p, "econ1_oat_min", 12.777778)
    fan = _fan(d)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    return (fan > FAN_ON_MIN) & d["outside-air-damper"].notna() & d["outside-air-temp"].notna() & (econ < 0.05) & (d["outside-air-temp"] > oat_min)


def econ2(d, p, poll):
    oat_hi = _f(p, "econ2_oat_hi", 17.222222)
    dmpr = _f(p, "econ2_damper", 0.42)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    return d["outside-air-temp"].notna() & d["outside-air-damper"].notna() & (d["outside-air-temp"] > oat_hi) & (econ > dmpr)


def econ4(d, p, poll):
    oa_min_pct = _f(p, "oa_min_pct", 21.0)
    rat_oat_min = _f(p, "oat_rat_delta_min", 1.2222222222222223)
    fan = _fan(d)
    oa_frac = (d["mixed-air-temp"] - d["return-air-temp"]) / (d["outside-air-temp"] - d["return-air-temp"]).replace(0, np.nan) * 100.0
    return (
        (fan > FAN_ON_MIN) & d["mixed-air-temp"].notna() & d["return-air-temp"].notna() & d["outside-air-temp"].notna()
        & ((d["return-air-temp"] - d["outside-air-temp"]).abs() > rat_oat_min) & (oa_frac < oa_min_pct)
    )


def econ5(d, p, poll):
    over = _f(p, "preheat_over", 1.222222)
    return (
        d["preheat-leaving-temp"].notna() & d["discharge-air-temp-sp"].notna() & d["outside-air-temp"].notna() & d["heating-valve"].notna()
        & (norm_cmd(d["heating-valve"]).fillna(0) > 0.01)
        & (
            ((d["outside-air-temp"] > d["discharge-air-temp-sp"]) & (d["preheat-leaving-temp"] - d["outside-air-temp"] > over))
            | ((d["outside-air-temp"] < d["discharge-air-temp-sp"]) & (d["preheat-leaving-temp"] - d["discharge-air-temp-sp"] > over))
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
    if "zone-airflow" in d.columns:
        thr = _param_si_flow_to_series(d, flow_min)
        return pd.to_numeric(d["zone-airflow"], errors="coerce").fillna(0) > thr
    return pd.Series(True, index=d.index)


def _unoccupied_mask(d: pd.DataFrame) -> pd.Series:
    col = next((c for c in ("occupied", "occ-mode") if c in d.columns), None)
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
    if any(c in d.columns and d[c].notna().any() for c in ("occupied", "occ-mode")):
        return (~_unoccupied_mask(d)).fillna(False), "occupied"
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
    lo = _param_si_abs_temp_to_series(d, "zone-air-temp", _f(p, "zone_lo", 21.111111))
    hi = _param_si_abs_temp_to_series(d, "zone-air-temp", _f(p, "zone_hi", 23.888889))
    zt = pd.to_numeric(d["zone-air-temp"], errors="coerce")
    occupied, _src = vav1_occupied_mask(d, p)
    return zt.notna() & ((zt < lo) | (zt > hi)) & occupied


def vav2(d, p, poll):
    """Unoccupied zone stays warmer than heating setback (night setback miss)."""
    hi = _param_si_abs_temp_to_series(d, "zone-air-temp", _f(p, "setback_hi", 20.0))
    zt = pd.to_numeric(d["zone-air-temp"], errors="coerce")
    return zt.notna() & _unoccupied_mask(d) & (zt > hi)


def vav3(d, p, poll):
    oat_hi = _param_si_abs_temp_to_series(d, "outside-air-temp", _f(p, "reheat_oat", 25.555556))
    reheat_thr = _f(p, "reheat_pct", 0.52)
    flow_min = _f(p, "flow_on_min", 11.798689)
    reheat = norm_cmd(d["reheat-valve"]).fillna(0)
    return _vav_air_on(d, flow_min) & d["outside-air-temp"].notna() & (d["outside-air-temp"] > oat_hi) & (reheat > reheat_thr)


def vav4(d, p, poll):
    full_open = _f(p, "full_open_pct", 0.975)
    hours = _f(p, "sustain_hours", 1.5)
    flow_min = _f(p, "flow_on_min", 11.798689)
    roll = max(2, int(round(hours * 3600 / max(poll, 1))))
    dmp = norm_cmd(d["damper"]).fillna(0)
    return (
        _vav_air_on(d, flow_min) & dmp.notna() & (dmp > full_open)
        & (dmp.rolling(roll, min_periods=roll).min() > full_open)
    )


def vav5(d, p, poll):
    dmp = norm_cmd(d["damper"]).fillna(0)
    flow_thr = _param_si_flow_to_series(d, 23.597372)
    return d["zone-airflow"].notna() & (d["zone-airflow"] > flow_thr) & (dmp < 0.10)


def vav6(d, p, poll):
    """Reheat open while OA is cool enough for free cooling."""
    oat_hi = _param_si_abs_temp_to_series(d, "outside-air-temp", _f(p, "free_cool_oat", 18.333333))
    reheat_thr = _f(p, "reheat_pct", 0.25)
    reheat = norm_cmd(d["reheat-valve"]).fillna(0)
    oat = pd.to_numeric(d["outside-air-temp"], errors="coerce")
    clg = pd.Series(True, index=d.index)
    if "cooling-available" in d.columns and d["cooling-available"].notna().any():
        clg = as_bool(d["cooling-available"])
    return oat.notna() & clg.fillna(False) & (oat < oat_hi) & (reheat > reheat_thr)


def vav7(d, p, poll):
    """Min-flow violation OR fixed/high airflow while air is moving (mins too high / no modulate)."""
    under = (
        d["zone-airflow"].notna() & d["min-flow-sp"].notna() & (d["zone-airflow"] < d["min-flow-sp"])
        if "min-flow-sp" in d.columns
        else _false(d.index)
    )
    flow = pd.to_numeric(d["zone-airflow"], errors="coerce") if "zone-airflow" in d.columns else None
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
    if "min-flow-sp" in d.columns:
        high_min_thr = _param_si_flow_to_series(d, _f(p, "high_min_flow_sp", 117.986861))
        high_min = (
            air_on
            & d["min-flow-sp"].notna()
            & (pd.to_numeric(d["min-flow-sp"], errors="coerce") > high_min_thr)
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
        d, "vav-discharge-air-temp", _f(p, "min_rise", 1.666667)
    )
    flow_min = _f(p, "flow_on_min", 11.798689)
    reheat = norm_cmd(d["reheat-valve"]).fillna(0)
    rise = d["vav-discharge-air-temp"] - d["vav-inlet-air-temp"]
    return (
        _vav_air_on(d, flow_min)
        & d["vav-discharge-air-temp"].notna() & d["vav-inlet-air-temp"].notna()
        & (reheat > cmd_thr) & (rise < min_rise)
    )


def vav_vs_ahu_leave(d, p, poll):
    """VAV leave temp far from parent AHU SAT (fedBy) — broken reheat or sensor/rogue box.

    Requires topology enrich: ``ahu_sat`` copied from parent AHU onto the VAV frame.
    Without ``ahu_sat``, the rule is SKIPPED_MISSING_ROLES by the engine.
    """
    band = _param_si_delta_temp_to_series(d, "vav-discharge-air-temp", _f(p, "delta", 4.444444))
    flow_min = _f(p, "flow_on_min", 11.798689)
    leave = pd.to_numeric(d["vav-discharge-air-temp"], errors="coerce")
    ahu = pd.to_numeric(d["ahu-discharge-air-temp"], errors="coerce")
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
    if "fan-status" in d.columns:
        status = as_bool(d["fan-status"])
        if "fan-cmd" in d.columns:
            command = norm_cmd(d["fan-cmd"]).fillna(0) > 0.10
            return status.where(d["fan-status"].notna(), command)
        return status
    if "fan-cmd" in d.columns:
        return norm_cmd(d["fan-cmd"]).fillna(0) > 0.10
    return _false(d.index)


def fcu_sensor_null(d, p, poll):
    if "zone-air-temp" not in d.columns:
        return pd.Series(False, index=d.index)
    zone = pd.to_numeric(d["zone-air-temp"], errors="coerce")
    sp = pd.to_numeric(d["zone-air-temp-sp"], errors="coerce")
    eligible = sp.notna()
    null_fraction = float(zone[eligible].isna().mean()) if eligible.any() else 0.0
    return eligible & zone.isna() & (null_fraction >= _f(p, "null_fraction", 0.90))


def fcu_htg_coil(d, p, poll):
    heat = norm_cmd(d["heating-valve"])
    rise = pd.to_numeric(d["discharge-air-temp"], errors="coerce") - pd.to_numeric(
        d["zone-air-temp"], errors="coerce"
    )
    coil_delta = _param_si_delta_temp_to_series(
        d, "discharge-air-temp", _f(p, "coil_delta", 3.0)
    )
    return _fcu_fan_on(d) & heat.notna() & (heat >= _f(p, "valve_open", 0.80)) & (rise < coil_delta)


def fcu_clg_coil(d, p, poll):
    cool = norm_cmd(d["cooling-valve"])
    heat = norm_cmd(d["heating-valve"])
    rise = pd.to_numeric(d["discharge-air-temp"], errors="coerce") - pd.to_numeric(
        d["zone-air-temp"], errors="coerce"
    )
    return _fcu_fan_on(d) & cool.notna() & heat.notna() & (cool >= _f(p, "valve_open", 0.80)) & (heat <= 0.05) & (rise >= 0)


def fcu_valve_pass_htg(d, p, poll):
    heat = norm_cmd(d["heating-valve"])
    cool = norm_cmd(d["cooling-valve"])
    rise = pd.to_numeric(d["discharge-air-temp"], errors="coerce") - pd.to_numeric(
        d["zone-air-temp"], errors="coerce"
    )
    pass_delta = _param_si_delta_temp_to_series(
        d, "discharge-air-temp", _f(p, "pass_delta", 3.0)
    )
    return _fcu_fan_on(d) & heat.notna() & cool.notna() & (heat <= 0.05) & (cool <= 0.05) & (rise > pass_delta)


def fcu_valve_pass_clg(d, p, poll):
    heat = norm_cmd(d["heating-valve"])
    cool = norm_cmd(d["cooling-valve"])
    drop = pd.to_numeric(d["zone-air-temp"], errors="coerce") - pd.to_numeric(
        d["discharge-air-temp"], errors="coerce"
    )
    pass_delta = _param_si_delta_temp_to_series(
        d, "discharge-air-temp", _f(p, "pass_delta", 3.0)
    )
    return _fcu_fan_on(d) & heat.notna() & cool.notna() & (heat <= 0.05) & (cool <= 0.05) & (drop > pass_delta)


def fcu_damper_pos(d, p, poll):
    cmd = norm_cmd(d["damper-cmd"])
    pos = norm_cmd(d["damper"])
    return _fcu_fan_on(d) & (cmd >= _f(p, "command_min", 0.15)) & ((cmd - pos) > _f(p, "position_error", 0.15))


def fcu_co2_damper(d, p, poll):
    co2 = pd.to_numeric(d["zone-co2"], errors="coerce")
    cmd = norm_cmd(d["damper-cmd"])
    return _fcu_fan_on(d) & (co2 > _f(p, "co2_high_ppm", 1000.0)) & (co2 >= 300.0) & (cmd < _f(p, "damper_low", 0.10))


def fcu_deadband(d, p, poll):
    cool = pd.to_numeric(d["cooling-sp"], errors="coerce")
    heat = pd.to_numeric(d["heating-sp"], errors="coerce")
    band = _param_si_delta_temp_to_series(d, "zone-air-temp", _f(p, "deadband", 1.0))
    return cool.notna() & heat.notna() & ((cool - heat) < band)


def fcu_mode_cycle(d, p, poll):
    heat = norm_cmd(d["heating-valve"])
    cool = norm_cmd(d["cooling-valve"])
    mode = pd.Series(0, index=d.index, dtype=int)
    mode = mode.mask(heat > _f(p, "mode_valve_min", 0.10), 1)
    mode = mode.mask(cool > _f(p, "mode_valve_min", 0.10), -1)
    active = mode.where(mode != 0).ffill().fillna(0)
    changes = ((active != active.shift()) & (active != 0) & (active.shift().fillna(0) != 0)).astype(int).cumsum()
    # Idle samples are omitted from the transition sequence and must not become
    # fault rows after the threshold is crossed.
    return (mode != 0) & (changes >= int(_f(p, "mode_changes", 4.0)))


# ---------------------------------------------------------------------------
# Central plants
# ---------------------------------------------------------------------------


def chw1(d, p, poll):
    min_dt = _f(p, "min_dt", 2.222222)
    dt = d["chilled-water-return-temp"] - d["chilled-water-supply-temp"]
    return (
        d["chilled-water-supply-temp"].notna()
        & d["chilled-water-return-temp"].notna()
        & (dt < min_dt)
    )


def chw2(d, p, poll):
    margin = _f(p, "dp_margin", 15168.465)
    pmp_hi = _f(p, "pump_hi", 0.87)
    pump = norm_cmd(d["chw-pump-cmd"]).fillna(0)
    return (
        d["chw-diff-pressure"].notna() & d["chw-diff-pressure-sp"].notna()
        & (d["chw-diff-pressure"] < d["chw-diff-pressure-sp"] - margin) & (pump >= pmp_hi)
    )


def chw3(d, p, poll):
    band = _f(p, "sp_band", 1.222222)
    pump = norm_cmd(d["chw-pump-cmd"]).fillna(0)
    return (
        (pump > 0.01) & d["chilled-water-supply-temp"].notna() & d["chilled-water-supply-temp-sp"].notna()
        & ((d["chilled-water-supply-temp"] < d["chilled-water-supply-temp-sp"] - band) | (d["chilled-water-supply-temp"] > d["chilled-water-supply-temp-sp"] + band))
    )


def chw4(d, p, poll):
    flow_hi = _f(p, "flow_hi", 69.3992)
    pmp_hi = _f(p, "pump_hi", 0.87)
    pump = norm_cmd(d["chw-pump-cmd"]).fillna(0)
    return d["chw-flow"].notna() & (d["chw-flow"] > flow_hi) & (pump >= pmp_hi)


# ---------------------------------------------------------------------------
# Heat pumps
# ---------------------------------------------------------------------------


def hp1(d, p, poll):
    min_sat = _f(p, "min_sat", 29.4444)
    zone_cold = _f(p, "zone_cold", 20.5556)
    fan = _fan(d)
    return (
        d["discharge-air-temp"].notna() & d["zone-air-temp"].notna() & (fan > FAN_ON_MIN)
        & (d["zone-air-temp"] < zone_cold) & (d["discharge-air-temp"] < min_sat)
    )


# ---------------------------------------------------------------------------
# Weather station
# ---------------------------------------------------------------------------


def wx1(d, p, poll):
    """OAT sample-to-sample spike; limit scales with the sample gap vs poll."""
    spike = _f(p, "spike_limit", 8.888889)
    s = pd.to_numeric(d["outside-air-temp"], errors="coerce")
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
    if "condenser-water-supply-temp" not in d.columns:
        return _false(d.index)
    wb = d["web-outside-air-wetbulb"] if "web-outside-air-wetbulb" in d.columns else None
    if wb is None or wb.notna().sum() == 0:
        return _false(d.index)
    approach = _f(p, "cw_approach", 3.888889)
    slack = _f(p, "cw_slack", 1.111111)
    # Over-cooled tower water: supply significantly below wet-bulb + design approach
    return (
        d["condenser-water-supply-temp"].notna()
        & wb.notna()
        & (pd.to_numeric(d["condenser-water-supply-temp"], errors="coerce") < (wb + approach - slack))
    )


def _tower_fan_full_mask(d: pd.DataFrame, p: dict) -> pd.Series:
    """True when tower / CW fan command is at/near full speed (0–1 or 0–100%)."""
    thr = _f(p, "tower_fan_hi", 0.95)
    for role in ("tower-fan-cmd", "cw-fan-cmd", "fan-cmd"):
        if role in d.columns and d[role].notna().any():
            return norm_cmd(d[role]).fillna(0) >= thr
    return _false(d.index)


def _cw_approach(d: pd.DataFrame) -> pd.Series:
    """Leaving CW minus web wet-bulb (°C difference)."""
    cw = pd.to_numeric(d["condenser-water-supply-temp"], errors="coerce")
    wb = pd.to_numeric(d["web-outside-air-wetbulb"], errors="coerce")
    return cw - wb


def cw_apr(d, p, poll):
    """High CW approach at full tower fan — sensors or tower degradation."""
    if "condenser-water-supply-temp" not in d.columns:
        return _false(d.index)
    if "web-outside-air-wetbulb" not in d.columns or d["web-outside-air-wetbulb"].notna().sum() == 0:
        return _false(d.index)
    if not any(r in d.columns and d[r].notna().any() for r in ("tower-fan-cmd", "cw-fan-cmd", "fan-cmd")):
        return _false(d.index)
    limit = _f(p, "approach_max", 4.444444)
    apr = _cw_approach(d)
    return (
        d["condenser-water-supply-temp"].notna()
        & d["web-outside-air-wetbulb"].notna()
        & _tower_fan_full_mask(d, p)
        & (apr > limit)
    )


def cw_fan_excess(d, p, poll):
    """Excess tower-fan energy — CW well above theoretical WB+approach at full fan."""
    if "condenser-water-supply-temp" not in d.columns:
        return _false(d.index)
    if "web-outside-air-wetbulb" not in d.columns or d["web-outside-air-wetbulb"].notna().sum() == 0:
        return _false(d.index)
    if not any(r in d.columns and d[r].notna().any() for r in ("tower-fan-cmd", "cw-fan-cmd", "fan-cmd")):
        return _false(d.index)
    approach = _f(p, "cw_approach", 3.888889)
    excess = _f(p, "excess_beyond_approach", 2.777778)
    apr = _cw_approach(d)
    return (
        d["condenser-water-supply-temp"].notna()
        & d["web-outside-air-wetbulb"].notna()
        & _tower_fan_full_mask(d, p)
        & (apr > (approach + excess))
    )


def oat_vs_meteo(d, p, poll):
    """BAS outdoor-air sensor disagrees with Open-Meteo dry bulb by more than the threshold."""
    if "web-outside-air-temp" not in d.columns and "web_oat_native_frame" not in d.attrs:
        return _false(d.index)
    err = _f(p, "oat_err", 2.777778)
    cadence = _f(p, "web_cadence_seconds", 1200.0)
    margin = _f(p, "web_asof_margin_seconds", 300.0)
    bound_s = cadence + margin
    bas = pd.to_numeric(d["outside-air-temp"], errors="coerce")
    if not isinstance(d.index, pd.DatetimeIndex):
        web = pd.to_numeric(d["web-outside-air-temp"], errors="coerce")
        return bas.notna() & web.notna() & (bas.sub(web).abs() > err)
    web_native = d.attrs.get("web_oat_native_frame")
    if isinstance(web_native, pd.DataFrame) and "web-outside-air-temp" in web_native.columns:
        web_src = web_native[["web-outside-air-temp"]].sort_index()
    else:
        web_src = pd.DataFrame({"web-outside-air-temp": pd.to_numeric(d["web-outside-air-temp"], errors="coerce")})
        web_src.index = d.index
        web_src = web_src.dropna().sort_index()
    left = pd.DataFrame({"outside-air-temp": bas}).sort_index()
    merged = pd.merge_asof(
        left,
        web_src,
        left_index=True,
        right_index=True,
        direction="backward",
        tolerance=pd.Timedelta(seconds=bound_s),
    )
    web_aligned = merged["web-outside-air-temp"]
    assessed = bas.notna() & web_aligned.notna()
    return assessed & (bas.sub(web_aligned).abs() > err)


# ---------------------------------------------------------------------------
# Trim & respond advisory
# ---------------------------------------------------------------------------


def trim1(d, p, poll):
    duct_hi = _f(p, "duct_hi", 335.934)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["duct-static-pressure"].notna() & d["vav-pressure-request-sum"].notna()
        & (d["duct-static-pressure"] > duct_hi) & (d["vav-pressure-request-sum"] < req_lo)
    )


def trim3(d, p, poll):
    hwst_hi = _f(p, "hwst_hi", 71.1111)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["hot-water-supply-temp"].notna() & d["hw-reset-request-sum"].notna()
        & (d["hot-water-supply-temp"] > hwst_hi) & (d["hw-reset-request-sum"] < req_lo)
    )


def trim4(d, p, poll):
    chw_lo = _f(p, "chw_lo", 7.222222)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["chilled-water-supply-temp"].notna() & d["chw-reset-request-sum"].notna()
        & (d["chilled-water-supply-temp"] < chw_lo) & (d["chw-reset-request-sum"] < req_lo)
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
    oat = pd.to_numeric(d["outside-air-temp"], errors="coerce")
    sat_sp = pd.to_numeric(d["discharge-air-temp-sp"], errors="coerce")
    expected = intercept + slope * (oat - oat_ref)
    fan = pd.Series(True, index=d.index)
    if "fan-status" in d.columns and d["fan-status"].notna().any():
        fan = as_bool(d["fan-status"])
    elif "fan-cmd" in d.columns:
        fan = norm_cmd(d["fan-cmd"]).fillna(0) > 0.05
    return sat_sp.notna() & oat.notna() & fan.fillna(False) & ((sat_sp - expected).abs() > err)


def sched1(d, p, poll):
    """Unoccupied fan runtime; optional zone comfort band when zone_t is mapped.

    Portable occupancy: literal ``unoccupied`` (case-insensitive) **or** numeric /
    boolean falsey values (``0``, ``0.0``, ``False``). String ``"1"`` / occupied
    labels are treated as occupied.
    """
    if "occupied" not in d or "fan-status" not in d:
        return _false(d.index)
    occ_raw = d["occupied"]
    occ_str = occ_raw.astype(str).str.strip().str.lower()
    label_unocc = occ_str.isin(
        {"unoccupied", "unocc", "off", "false", "night", "standby", "setback", "no"}
    )
    occ_num = pd.to_numeric(occ_raw, errors="coerce")
    numeric_unocc = occ_num.notna() & (occ_num <= 0.05)
    unoccupied = label_unocc | numeric_unocc
    base = unoccupied & as_bool(d["fan-status"])
    if "zone-air-temp" not in d.columns or d["zone-air-temp"].notna().sum() == 0:
        return base
    lo = _f(p, "comfort_low", 21.111111)
    hi = _f(p, "comfort_high", 23.888889)
    zt = pd.to_numeric(d["zone-air-temp"], errors="coerce")
    in_band = zt.notna() & (zt >= lo) & (zt <= hi)
    return base & in_band


def cmd1(d, p, poll):
    cmd_on = norm_cmd(d["fan-cmd"]).fillna(0) >= 0.05
    return d["fan-status"].notna() & (cmd_on != as_bool(d["fan-status"]))


def oa1(d, p, poll):
    min_oa = _f(p, "min_oa_frac", 0.15)
    guard = _f(p, "oat_rat_guard", 1.2222222222222223)
    oa_frac = (d["mixed-air-temp"] - d["return-air-temp"]) / (d["outside-air-temp"] - d["return-air-temp"]).replace(0, np.nan)
    fan = _fan(d)
    return (
        (fan > FAN_ON_MIN) & d["outside-air-temp"].notna() & d["return-air-temp"].notna() & d["mixed-air-temp"].notna()
        & ((d["return-air-temp"] - d["outside-air-temp"]).abs() > guard) & (oa_frac < min_oa)
    )


def dmp1(d, p, poll):
    leak_delta = _f(p, "leak_delta", 1.111111)
    dmp = norm_cmd(d["outside-air-damper"]).fillna(0)
    return d["outside-air-temp"].notna() & d["mixed-air-temp"].notna() & (dmp <= 0.05) & (d["mixed-air-temp"].sub(d["outside-air-temp"]).abs() < leak_delta)


def vlv1(d, p, poll):
    """Cooling valve leak: valve closed AND (SAT low vs SP or SAT low vs MAT).

    Fan proven-on is enforced by the VLV-1 operational gate when fan_status/fan_cmd exist.
    """
    sat_err = _f(p, "sat_err", 1.111111)
    mat_delta = _f(p, "mat_leak_delta", 1.111111)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    closed = clg <= 0.05
    sat = pd.to_numeric(d["discharge-air-temp"], errors="coerce")
    sat_sp = pd.to_numeric(d["discharge-air-temp-sp"], errors="coerce")
    below_sp = sat.notna() & sat_sp.notna() & (sat < sat_sp - sat_err)
    below_mat = pd.Series(False, index=d.index)
    if "mixed-air-temp" in d.columns and d["mixed-air-temp"].notna().any():
        mat = pd.to_numeric(d["mixed-air-temp"], errors="coerce")
        below_mat = sat.notna() & mat.notna() & (sat < mat - mat_delta)
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
        "SV-STALE", "Stale data (no fresh samples)", "sensor",
        ["ahu", "vav", "chiller", "boiler", "weather", "zone_other", "heatpump"], [],
        "All modeled sensors unchanged over the stale window — data feed likely dropped.",
        _sweep_stale, params=[
            CookbookParam("stale_hours", "Stale window", "h", 0.25, 12.0, 0.25, 2.0),
            CookbookParam("stale_tol", "Stale tolerance", "Δ°C", 0.0, 0.555556, 0.005556, 0.027778),
            CookbookParam("max_silence_hours", "Max sensor silence", "h", 0.25, 12.0, 0.25, 0.5),
            CONFIRM_PARAM(),
        ], sensor_sweep=True, confirm_seconds=300,
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
        optional_roles=["loop-enabled"],
        control_output_sweep=True,
        confirm_seconds=0,
    ),

    # --- AHU GL36 (FC1–FC15) ---
    CookbookRule("FC1", "Duct static below SP at full fan (GL36 A)", "ahu", ["ahu"],
        ["duct-static-pressure", "duct-static-pressure-sp", "fan-cmd"],
        "DSP < DSPSP − εDSP AND VFDSPD ≥ 100% − εVFDSPD.",
        fc1, params=[
            CookbookParam("eps_dsp", "Duct-static error εDSP", "Pa", 0.0, 124.42, 2.4884, 29.8608),
            CookbookParam("eps_vfd_spd", "VFD speed error εVFDSPD (GL36 default 5%)", "frac", 0.0, 0.5, 0.01, 0.13),
            CookbookParam("duct_static_err", "Legacy duct-static error (sets εDSP)", "Pa", 0.0, 124.42, 2.4884, 29.8608),
            CookbookParam("fan_hi", "Legacy fan-high threshold (sets εVFDSPD)", "frac", 0.5, 1.0, 0.01, 0.87),
            MODE_DELAY_PARAM(),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("FC2", "MAT below OAT/RAT envelope (GL36 B)", "ahu", ["ahu"],
        ["mixed-air-temp", "outside-air-temp", "return-air-temp", "fan-cmd"],
        "MATavg + εMAT < min(RATavg − εRAT, OATavg − εOAT).",
        fc2, params=[
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            EPS_TEMP_PARAM("eps_rat", "RAT sensor error εRAT"),
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT"),
            LEGACY_MIX_PARAM(), FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC3", "MAT above OAT/RAT envelope (GL36 C)", "ahu", ["ahu"],
        ["mixed-air-temp", "outside-air-temp", "return-air-temp", "fan-cmd"],
        "MATavg − εMAT > max(RATavg + εRAT, OATavg + εOAT).",
        fc3, params=[
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            EPS_TEMP_PARAM("eps_rat", "RAT sensor error εRAT"),
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT"),
            LEGACY_MIX_PARAM(), FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC4", "PID hunting (operating-state oscillation)", "ahu", ["ahu"],
        ["outside-air-damper", "cooling-valve", "fan-cmd"],
        "ΔOS > ΔOSmax during the prior 60-minute moving window.",
        fc4, params=[
            CookbookParam("delta_os_max", "Max mode changes/hr ΔOSmax (GL36 default 7)", "count", 1, 30, 1, 5, direction="fewer"),
            MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=3600),
    CookbookRule("FC5", "SAT cold when heating commanded (GL36 D)", "ahu", ["ahu"],
        ["discharge-air-temp", "mixed-air-temp", "fan-cmd", "heating-valve"],
        "SATavg + εSAT ≤ MATavg − εMAT + ΔTSF while heating is commanded.",
        fc5, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            DELTA_TSF_PARAM(),
            CookbookParam("htg_on_min", "Heating-command ON threshold", "frac", 0.0, 0.25, 0.01, 0.01),
            LEGACY_MIX_PARAM(), FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC6", "Estimated OA fraction mismatch", "ahu", ["ahu"],
        ["mixed-air-temp", "outside-air-temp", "return-air-temp", "vav-total-airflow"],
        "|RATavg−OATavg| ≥ ΔTmin AND |estimated OA% − design min OA%| > εF.",
        fc6, params=[
            CookbookParam("eps_airflow", "Airflow error εF (GL36 default 30%)", "frac", 0.05, 1.0, 0.01, 0.15),
            CookbookParam("delta_t_min", "Minimum |OAT−RAT| ΔTmin", "Δ°C", 0.0, 16.666667, 0.277778, 2.777778),
            CookbookParam("airflow_err", "Legacy OA-fraction error (sets εF)", "frac", 0.05, 1.0, 0.01, 0.15),
            CookbookParam("oat_rat_delta_min", "Legacy OAT/RAT guard (sets ΔTmin)", "°C", 0.0, 16.666667, 0.277778, 2.777778),
            CookbookParam("min_flow_design", "Design minimum outdoor airflow", "L/s", 0.0, 94389.4, 47.1947, 2359.735),
            FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC7", "SAT low with full heating (GL36 E)", "ahu", ["ahu"],
        ["discharge-air-temp", "discharge-air-temp-sp", "fan-cmd", "heating-valve"],
        "SATavg < SATSP − εSAT AND HC ≥ full-heating threshold.",
        fc7, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            CookbookParam("sat_err", "Legacy SAT error (sets εSAT)", "Δ°C", 0.0, 5.555556, 0.138889, 0.555556),
            CookbookParam("htg_full_min", "Full-heating threshold (GL36 99%)", "frac", 0.5, 1.0, 0.01, 0.90),
            FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC8", "SAT/MAT mismatch in economizer (GL36)", "ahu", ["ahu"],
        ["discharge-air-temp", "mixed-air-temp", "outside-air-damper", "cooling-valve"],
        "|SATavg − ΔTSF − MATavg| > √(εSAT² + εMAT²) in OS#2.",
        fc8, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), CLG_INACTIVE_PARAM(),
            LEGACY_MIX_PARAM(), LEGACY_SUPPLY_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC9", "OAT too warm for free cooling (GL36 G)", "ahu", ["ahu"],
        ["outside-air-temp", "discharge-air-temp-sp", "outside-air-damper", "cooling-valve"],
        "OATavg − εOAT > SATSP − ΔTSF + εSAT in OS#2.",
        fc9, params=[
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT"),
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), CLG_INACTIVE_PARAM(),
            LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC10", "OAT/MAT mismatch + mech cooling (GL36 H)", "ahu", ["ahu"],
        ["mixed-air-temp", "outside-air-temp", "outside-air-damper", "cooling-valve"],
        "|MATavg − OATavg| > √(εMAT² + εOAT²) in OS#3.",
        fc10, params=[
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT"),
            ECON_FULL_PARAM(), CLG_ON_PARAM(), LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC11", "OAT/MAT mismatch economizer-only (GL36 I)", "ahu", ["ahu"],
        ["outside-air-temp", "discharge-air-temp-sp", "outside-air-damper", "cooling-valve"],
        "OATavg + εOAT < SATSP − ΔTSF − εSAT in OS#3.",
        fc11, params=[
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT"),
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            DELTA_TSF_PARAM(), ECON_FULL_PARAM(), CLG_ON_PARAM(),
            LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC12", "SAT above blend in cooling (GL36 J)", "ahu", ["ahu"],
        ["discharge-air-temp", "mixed-air-temp", "outside-air-damper", "cooling-valve"],
        "SATavg − εSAT − ΔTSF ≥ MATavg + εMAT in OS#3/OS#4.",
        fc12, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), ECON_FULL_PARAM(), CLG_ON_PARAM(),
            LEGACY_MIX_PARAM(), LEGACY_SUPPLY_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC13", "SAT above SP at full cooling (GL36 K)", "ahu", ["ahu"],
        ["discharge-air-temp", "discharge-air-temp-sp", "outside-air-damper", "cooling-valve"],
        "SATavg > SATSP + εSAT AND CC ≥ full-cooling threshold in OS#3/OS#4.",
        fc13, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT"),
            CookbookParam("sat_err", "Legacy SAT error (sets εSAT)", "Δ°C", 0.0, 5.555556, 0.138889, 0.555556),
            CookbookParam("clg_full_min", "Full-cooling threshold (GL36 99%)", "frac", 0.5, 1.0, 0.01, 0.01),
            ECON_MIN_PARAM(), ECON_FULL_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC14", "CHW coil ΔT when inactive (GL36 L)", "ahu", ["ahu"],
        ["cooling-coil-entering-temp", "cooling-coil-leaving-temp", "outside-air-damper", "cooling-valve"],
        "Cooling-coil ΔT ≥ √(εCCET² + εCCLT²) + ΔTSF while coil should be inactive.",
        fc14, params=[
            EPS_TEMP_PARAM("eps_ccet", "Cooling-coil entering sensor error εCCET"),
            EPS_TEMP_PARAM("eps_cclt", "Cooling-coil leaving sensor error εCCLT"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), CLG_INACTIVE_PARAM(),
            CookbookParam("htg_on_min", "Heating-command ON threshold", "frac", 0.0, 0.25, 0.01, 0.01),
            LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC15", "HW coil ΔT when inactive (GL36 M)", "ahu", ["ahu"],
        ["heating-coil-entering-temp", "heating-coil-leaving-temp", "outside-air-damper", "cooling-valve"],
        "Heating-coil ΔT ≥ √(εHCET² + εHCLT²) + ΔTSF while coil should be inactive.",
        fc15, params=[
            EPS_TEMP_PARAM("eps_hcet", "Heating-coil entering sensor error εHCET"),
            EPS_TEMP_PARAM("eps_hclt", "Heating-coil leaving sensor error εHCLT"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), ECON_FULL_PARAM(),
            CLG_INACTIVE_PARAM(), CLG_ON_PARAM(), LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),

    # --- AHU additional patterns ---
    CookbookRule("AHU-SATDEV", "SAT deviation from setpoint", "ahu", ["ahu"],
        ["discharge-air-temp", "discharge-air-temp-sp"], "|SAT − SAT SP| > 2.8 Δ°C.",
        ahu_sat_dev, params=[CookbookParam("sat_dev_err", "SAT deviation", "Δ°C", 0.555556, 8.333333, 0.277778, 2.777778, direction="fewer"), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("AHU-DUCTHI", "Duct static pressure high", "ahu", ["ahu"],
        ["duct-static-pressure", "duct-static-pressure-sp"],
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
        ["heating-valve", "cooling-valve"], "Heating valve > 10% AND cooling valve > 10% at once.",
        ahu_simul_heat_cool, params=[CookbookParam("valve_open_pct", "Valve open threshold", "frac", 0.05, 0.5, 0.01, 0.10), CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("OAT-METEO", "BAS outdoor-air sensor vs Open-Meteo", "ahu", ["ahu"],
        ["outside-air-temp", "web-outside-air-temp"], "BAS OAT sensor differs from Open-Meteo dry bulb by more than 2.8 Δ°C.",
        oat_vs_meteo, params=[
            CookbookParam("oat_err", "Max OAT disagreement", "°C", 1.111111, 11.111111, 0.277778, 2.777778, direction="fewer"),
            CookbookParam("web_cadence_seconds", "Web weather cadence", "sec", 300.0, 7200.0, 300.0, 1200.0),
            CookbookParam("web_asof_margin_seconds", "Web as-of margin", "sec", 0.0, 1800.0, 60.0, 300.0),
            CONFIRM_PARAM()], confirm_seconds=900),

    # --- Economizer & ventilation ---
    CookbookRule("ECON-1", "Economizer stuck closed", "ahu", ["ahu"],
        ["fan-cmd", "outside-air-damper", "outside-air-temp"], "Fan on, OA damper < 5%, OAT > 12.8 °C (should be economizing).",
        econ1, params=[CookbookParam("econ1_oat_min", "Favorable OAT", "°C", 7.222222, 21.111111, 0.555556, 12.777778), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("ECON-2", "Economizing when outdoor unfavorable", "ahu", ["ahu"],
        ["outside-air-temp", "outside-air-damper"], "OAT > 17.2 °C AND OA damper > 42% (should be at minimum).",
        econ2, params=[
            CookbookParam("econ2_oat_hi", "OAT high cutoff", "°C", 12.777778, 26.666667, 0.555556, 17.222222),
            CookbookParam("econ2_damper", "Damper open frac", "frac", 0.2, 0.9, 0.02, 0.42),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule(
        "ECON-3",
        "Mech cooling without integrated economizer",
        "ahu",
        ["ahu"],
        ["outside-air-damper", "cooling-valve"],
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
        optional_roles=["web-outside-air-temp", "web-outside-air-dewpoint", "web-outside-air-humidity"],
        confirm_seconds=300,
    ),
    CookbookRule("ECON-4", "Low estimated OA fraction", "ahu", ["ahu"],
        ["mixed-air-temp", "return-air-temp", "outside-air-temp", "fan-cmd"], "Fan on, |RAT−OAT| > 1.2 Δ°C, estimated OA fraction < 21%.",
        econ4, params=[CookbookParam("oa_min_pct", "Min OA fraction", "%", 5.0, 40.0, 1.0, 21.0, direction="stricter"), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("ECON-5", "Preheat over-conditioning", "ahu", ["ahu"],
        ["preheat-leaving-temp", "discharge-air-temp-sp", "outside-air-temp", "heating-valve"], "Preheat leaving air > 1.2°C above target while preheat active.",
        econ5, params=[CookbookParam("preheat_over", "Preheat over ΔT", "Δ°C", 0.277778, 4.444444, 0.055556, 1.222222, direction="fewer"), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule(
        "ECON-6",
        "Economizing in freezing weather",
        "ahu",
        ["ahu"],
        ["outside-air-damper"],
        "Web dry-bulb < −3.9°C AND OA damper above winter min-OA ceiling (default 25%). "
        "AHU should be at minimum OA in cold weather.",
        __import__("open_fdd.rules.economizer_weather", fromlist=["econ6_compute"]).econ6_compute,
        params=[
            CookbookParam("econ6_oat_max", "Winter OAT ceiling", "°C", -9.444444, 4.444444, 0.555556, -3.888889),
            CookbookParam("econ6_damper_max", "Winter min-OA damper", "frac", 0.05, 0.5, 0.01, 0.25),
            CONFIRM_PARAM(),
        ],
        optional_roles=["web-outside-air-temp"],
        confirm_seconds=600,
    ),
    CookbookRule(
        "ECON-7",
        "Economizer OK but not economizing",
        "ahu",
        ["ahu"],
        ["outside-air-damper"],
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
            "web-outside-air-temp",
            "web-outside-air-dewpoint",
            "web-outside-air-humidity",
            "cooling-valve",
            "compressor-status",
            "dx-cool-cmd",
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
            "web-outside-air-temp",
            "compressor-status",
            "chiller-status",
            "chw-pump-status",
            "dx-cool-cmd",
        ],
        confirm_seconds=600,
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
            "chiller-status",
            "chw-pump-status",
            "compressor-status",
            "building-zone-load-satisfied",
            "building-ahu-load-satisfied",
        ],
        confirm_seconds=1800,
    ),

    # --- Fan coils / standalone zone controllers ---
    CookbookRule("FCU-SENSOR-NULL", "Missing FCU zone sensor", "fcu", ["zone_other", "general", "ahu"],
        ["zone-air-temp-sp"],
        "Own zone setpoint is present while zone temperature is null for at least 90% of the window.",
        fcu_sensor_null, params=[
            CookbookParam("null_fraction", "Null fraction", "frac", 0.5, 1.0, 0.05, 0.90),
            CONFIRM_PARAM()], optional_roles=["zone-air-temp"], confirm_seconds=0),
    CookbookRule("FCU-HTG-COIL", "FCU heating coil under-delivery", "fcu", ["zone_other", "general", "ahu"],
        ["discharge-air-temp", "zone-air-temp", "heating-valve"],
        "Fan on and heating valve ≥80%, but discharge air is less than 3 Δ°C above zone temperature.",
        fcu_htg_coil, params=[
            CookbookParam("valve_open", "Valve open threshold", "frac", 0.5, 1.0, 0.05, 0.80),
            CookbookParam("coil_delta", "Minimum heating rise", "°C", 0.555556, 11.111111, 0.277778, 3.0),
            CONFIRM_PARAM()], optional_roles=["fan-status", "fan-cmd"], confirm_seconds=900),
    CookbookRule("FCU-CLG-COIL", "FCU cooling coil under-delivery", "fcu", ["zone_other", "general", "ahu"],
        ["discharge-air-temp", "zone-air-temp", "cooling-valve", "heating-valve"],
        "Fan on, cooling valve ≥80%, and heating shut, but discharge air is not below zone temperature.",
        fcu_clg_coil, params=[
            CookbookParam("valve_open", "Valve open threshold", "frac", 0.5, 1.0, 0.05, 0.80),
            CONFIRM_PARAM()], optional_roles=["fan-status", "fan-cmd"], confirm_seconds=900),
    CookbookRule("FCU-VALVE-PASS-HTG", "FCU heating valve passing", "fcu", ["zone_other", "general", "ahu"],
        ["discharge-air-temp", "zone-air-temp", "heating-valve", "cooling-valve"],
        "Fan on and both valves shut, but discharge air exceeds zone temperature by more than 3 Δ°C.",
        fcu_valve_pass_htg, params=[
            CookbookParam("pass_delta", "Passing temperature rise", "°C", 0.555556, 11.111111, 0.277778, 3.0),
            CONFIRM_PARAM()], optional_roles=["fan-status", "fan-cmd"], confirm_seconds=900),
    CookbookRule("FCU-VALVE-PASS-CLG", "FCU cooling valve passing", "fcu", ["zone_other", "general", "ahu"],
        ["discharge-air-temp", "zone-air-temp", "heating-valve", "cooling-valve"],
        "Fan on and both valves shut, but zone temperature exceeds discharge air by more than 3 Δ°C.",
        fcu_valve_pass_clg, params=[
            CookbookParam("pass_delta", "Passing temperature drop", "°C", 0.555556, 11.111111, 0.277778, 3.0),
            CONFIRM_PARAM()], optional_roles=["fan-status", "fan-cmd"], confirm_seconds=900),
    CookbookRule("FCU-DAMPER-POS", "FCU damper command/position mismatch", "fcu", ["zone_other", "general", "ahu"],
        ["damper-cmd", "damper"],
        "Fan on and damper command ≥15%, but feedback is more than 15 percentage points below command.",
        fcu_damper_pos, params=[
            CookbookParam("command_min", "Minimum damper command", "frac", 0.0, 1.0, 0.05, 0.15),
            CookbookParam("position_error", "Position error", "frac", 0.05, 0.5, 0.05, 0.15),
            CONFIRM_PARAM()], optional_roles=["fan-status", "fan-cmd"], confirm_seconds=900),
    CookbookRule("FCU-CO2-DAMPER", "FCU high CO2 with low outdoor-air command", "fcu", ["zone_other", "general", "ahu"],
        ["zone-co2", "damper-cmd"],
        "Fan on and valid CO₂ exceeds 1000 ppm while damper command remains below 10%.",
        fcu_co2_damper, params=[
            CookbookParam("co2_high_ppm", "High CO₂", "ppm", 600, 2000, 50, 1000),
            CookbookParam("damper_low", "Low damper command", "frac", 0.0, 0.5, 0.05, 0.10),
            CONFIRM_PARAM()], optional_roles=["fan-status", "fan-cmd"], confirm_seconds=900),
    CookbookRule("FCU-DEADBAND", "FCU heat/cool deadband collapse", "fcu", ["zone_other", "general", "ahu"],
        ["cooling-sp", "heating-sp"],
        "Pass-through cooling setpoint minus heating setpoint is less than 1°C.",
        fcu_deadband, params=[
            CookbookParam("deadband", "Minimum deadband", "°C", 0.0, 5.0, 0.1, 1.0),
            CONFIRM_PARAM()], confirm_seconds=0),
    CookbookRule("FCU-MODE-CYCLE", "FCU heating/cooling mode cycling", "fcu", ["zone_other", "general", "ahu"],
        ["heating-valve", "cooling-valve"],
        "At least four heating/cooling valve mode changes occur in the analysis window.",
        fcu_mode_cycle, params=[
            CookbookParam("mode_valve_min", "Active valve threshold", "frac", 0.0, 0.5, 0.05, 0.10),
            CookbookParam("mode_changes", "Mode changes", "count", 1, 20, 1, 4),
            CONFIRM_PARAM()], confirm_seconds=0),

    # --- VAV zones ---
    CookbookRule("VAV-1", "Zone comfort band", "vav", ["vav", "zone_other", "heatpump", "baseboard"],
        ["zone-air-temp"],
        "Zone temp outside zone_lo–zone_hi (default 21.1–23.9 °C) during occupied hours when an "
        "occupancy column or Overview calendar is set (require_occupied, default on). "
        "Unoccupied setback stays on VAV-2.",
        vav1, params=[
            CookbookParam("zone_lo", "Zone low", "°C", 12.777778, 22.222222, 0.5, 21.111111),
            CookbookParam("zone_hi", "Zone high", "°C", 22.222222, 29.444444, 0.5, 23.888889),
            CookbookParam("require_occupied", "Require occupied", "bool", 0.0, 1.0, 1.0, 1.0),
            CONFIRM_PARAM()],
        optional_roles=["occupied", "occ-mode"], confirm_seconds=900),
    CookbookRule("VAV-2", "Night setback miss", "vav", ["vav", "zone_other", "heatpump", "baseboard"],
        ["zone-air-temp", "occupied"],
        "Unoccupied AND zone temp > setback_hi (default 20 °C) — heating setback not taken.",
        vav2, params=[
            CookbookParam("setback_hi", "Setback high", "°C", 12.777778, 22.222222, 0.277778, 20.0),
            CONFIRM_PARAM()],
        optional_roles=["occ-mode"], confirm_seconds=900),
    CookbookRule("VAV-3", "Excessive reheat during warm weather", "vav", ["vav"],
        ["outside-air-temp", "reheat-valve"], "Air flowing AND OAT > 25.6 °C AND reheat valve > 52%.",
        vav3, params=[
            CookbookParam("reheat_oat", "Warm OAT", "°C", 18.333333, 32.222222, 0.555556, 25.555556),
            CookbookParam("reheat_pct", "Reheat frac", "frac", 0.1, 1.0, 0.02, 0.52),
            CookbookParam("flow_on_min", "Airflow-on min", "L/s", 0.0, 94.3894, 2.359735, 11.798675),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("VAV-4", "Damper stuck at full open", "vav", ["vav"],
        ["damper"], "Air flowing AND damper > 97.5% sustained across the window.",
        vav4, params=[
            CookbookParam("full_open_pct", "Full open frac", "frac", 0.8, 1.0, 0.005, 0.975),
            CookbookParam("sustain_hours", "Sustain window", "h", 0.5, 6.0, 0.5, 1.5),
            CookbookParam("flow_on_min", "Airflow-on min", "L/s", 0.0, 94.3894, 2.359735, 11.798675),
            CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("VAV-5", "Airflow sensor bias", "vav", ["vav"],
        ["zone-airflow", "damper"], "Airflow > ~24 L/s while damper < 10% (implausible flow).",
        vav5, params=[CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("VAV-6", "Reheat when cooling available", "vav", ["vav"],
        ["outside-air-temp", "reheat-valve"],
        "OAT < 18.3 °C AND reheat valve > 25% (optional cooling-available must be true when mapped).",
        vav6, params=[
            CookbookParam("free_cool_oat", "Free-cool OAT", "°C", 7.222222, 23.888889, 0.555556, 18.333333),
            CookbookParam("reheat_pct", "Reheat frac", "frac", 0.05, 1.0, 0.05, 0.25),
            CONFIRM_PARAM()],
        optional_roles=["cooling-available"], confirm_seconds=900),
    CookbookRule("VAV-REHEAT", "Reheat valve stuck / no temp rise", "vav", ["vav"],
        ["reheat-valve", "vav-discharge-air-temp", "vav-inlet-air-temp"],
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
        ["vav-discharge-air-temp", "ahu-discharge-air-temp"],
        "Air flowing AND |VAV discharge − parent AHU SAT| > band. "
        "Needs package topology (vav_to_ahu) so ahu_sat is enriched from the fedBy AHU; "
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
        ["zone-airflow"],
        "Flow below min SP (when mapped), OR airflow stays flat (low rolling std) at a high mean while air is on "
        "(mins too high / box never modulates), OR min_flow_sp itself is excessively high.",
        vav7, params=[
            CookbookParam("flow_on_min", "Airflow-on min", "L/s", 0.0, 94.3894, 2.359735, 11.798675),
            CookbookParam("fixed_flow_max_std", "Fixed-flow max std", "L/s", 0.471947, 37.75576, 0.471947, 7.079205),
            CookbookParam("fixed_flow_min_mean", "Fixed-flow min mean", "L/s", 23.59735, 943.894, 4.71947, 94.3894, direction="fewer"),
            CookbookParam("high_min_flow_sp", "High min-flow SP", "L/s", 23.59735, 943.894, 4.71947, 117.98675, direction="fewer"),
            CONFIRM_PARAM()], confirm_seconds=900),

    # --- Central plants ---
    CookbookRule("CHW-1", "Low chilled-water ΔT", "plant", ["chiller"],
        ["chilled-water-supply-temp", "chilled-water-return-temp"], "Pump on AND (CHWR − CHWS) < 2.2 Δ°C.",
        chw1, params=[CookbookParam("min_dt", "Min ΔT", "°C", 0.555556, 6.666667, 0.277778, 2.222222), CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("CHW-2", "DP below SP at max pump speed", "plant", ["chiller"],
        ["chw-diff-pressure", "chw-diff-pressure-sp", "chw-pump-cmd"], "Pump ≥ 87% AND CHW DP < DP SP − 2.2.",
        chw2, params=[
            CookbookParam("dp_margin", "DP margin", "Pa", 3447.379, 41368.542, 689.476, 15168.465),
            CookbookParam("pump_hi", "Pump high-speed threshold", "frac", 0.5, 1.0, 0.01, 0.87),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("CHW-3", "Plant supply temp outside deadband", "plant", ["chiller"],
        ["chilled-water-supply-temp", "chilled-water-supply-temp-sp", "chw-pump-cmd"], "Pump on AND |CHWS − CHWS SP| > 1.2 Δ°C.",
        chw3, params=[CookbookParam("sp_band", "SP band", "°C", 0.277778, 3.333333, 0.055556, 1.222222), CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("CHW-4", "Flow high at max pump", "plant", ["chiller"],
        ["chw-flow", "chw-pump-cmd"], "Pump ≥ 87% AND CHW flow > 69.4 L/s.",
        chw4, params=[
            CookbookParam("flow_hi", "Flow high", "L/s", 12.61804, 189.2706, 3.15451, 69.39922),
            CookbookParam("pump_hi", "Pump high-speed threshold", "frac", 0.5, 1.0, 0.01, 0.87),
            CONFIRM_PARAM()], confirm_seconds=300),

    # --- Heat pumps ---
    CookbookRule("HP-1", "Discharge cold when heating", "heatpump", ["heatpump"],
        ["discharge-air-temp", "zone-air-temp", "fan-cmd"], "Fan on, zone < 20.6 °C, discharge SAT < 29.4 °C.",
        hp1, params=[
            CookbookParam("min_sat", "Min heating SAT", "°C", 21.111111, 43.333333, 0.555556, 29.444444, direction="stricter"),
            CookbookParam("zone_cold", "Zone cold", "°C", 15.555556, 22.222222, 0.277778, 20.555556, direction="stricter"),
            CONFIRM_PARAM()], confirm_seconds=600),

    # --- Weather / condenser ---
    CookbookRule("WX-1", "OA temperature spike", "weather", ["weather"],
        ["outside-air-temp"], "OAT sample-to-sample jump > 8.9 Δ°C.",
        wx1, params=[CookbookParam("spike_limit", "Spike limit", "°C", 2.222222, 22.222222, 0.555556, 8.888889), CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("CW-OPT-1", "Condenser water not optimized vs wet-bulb", "plant", ["chiller", "cooling_tower"],
        ["condenser-water-supply-temp"],
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
        ["condenser-water-supply-temp"],
        "At full tower fan speed, leaving CW − web wet-bulb exceeds approach_max (default 4.44°C, typically 2.8–5.6°C). "
        "Suspect OA→wet-bulb / CW sensor mismatch or cooling-tower performance degradation.",
        cw_apr,
        params=[
            CookbookParam("approach_max", "Max approach at full fan", "°C", 2.777778, 8.333333, 0.277778, 4.444444),
            CookbookParam("tower_fan_hi", "Tower fan full-speed threshold", "frac", 0.8, 1.0, 0.01, 0.95),
            CONFIRM_PARAM(),
        ],
        optional_roles=["tower-fan-cmd", "cw-fan-cmd", "fan-cmd", "web-outside-air-wetbulb"],
        confirm_seconds=900,
    ),
    CookbookRule(
        "CW-FAN-1",
        "Excess tower fan energy vs wet-bulb limit",
        "plant",
        ["chiller", "cooling_tower"],
        ["condenser-water-supply-temp"],
        "Tower fans at full speed while leaving CW is well above web wet-bulb + design approach "
        "(approach + excess_beyond). Fans are chasing a CW temp that is theoretically hard/impossible — excess fan energy.",
        cw_fan_excess,
        params=[
            CookbookParam("cw_approach", "Design approach", "°C", 1.666667, 8.333333, 0.277778, 3.888889),
            CookbookParam("excess_beyond_approach", "Excess beyond approach", "°C", 1.111111, 11.111111, 0.277778, 2.777778),
            CookbookParam("tower_fan_hi", "Tower fan full-speed threshold", "frac", 0.8, 1.0, 0.01, 0.95),
            CONFIRM_PARAM(),
        ],
        optional_roles=["tower-fan-cmd", "cw-fan-cmd", "fan-cmd", "web-outside-air-wetbulb"],
        confirm_seconds=900,
    ),

    # --- Trim & respond advisory (lumped with AHU / plants) ---
    CookbookRule("TRIM-1", "Duct static trim advisory", "trim", ["ahu"],
        ["duct-static-pressure", "vav-pressure-request-sum"], "Duct static high (> 336 Pa) while VAV pressure requests are low.",
        trim1, params=[
            CookbookParam("duct_hi", "Duct static high", "Pa", 124.42, 746.52, 12.442, 335.934, direction="fewer"),
            CookbookParam("request_lo", "Request sum low", "count", 0.0, 10.0, 0.5, 1.0, direction="stricter"),
            CONFIRM_PARAM()], confirm_seconds=1800),
    CookbookRule("TRIM-3", "HWST trim advisory", "trim", ["boiler"],
        ["hot-water-supply-temp", "hw-reset-request-sum"], "HW supply > 71.1 °C while reset requests are low.",
        trim3, params=[
            CookbookParam("hwst_hi", "HWST high", "°C", 48.888889, 93.333333, 0.555556, 71.111111, direction="fewer"),
            CookbookParam("request_lo", "Request sum low", "count", 0.0, 10.0, 0.5, 1.0, direction="stricter"),
            CONFIRM_PARAM()], confirm_seconds=1800),
    CookbookRule("TRIM-4", "CHW plant reset advisory", "trim", ["chiller"],
        ["chilled-water-supply-temp", "chw-reset-request-sum"], "CHW supply < 7.2 °C while reset requests are low.",
        trim4, params=[
            CookbookParam("chw_lo", "CHWS low", "°C", 1.666667, 12.777778, 0.277778, 7.222222, direction="stricter"),
            CookbookParam("request_lo", "Request sum low", "count", 0.0, 10.0, 0.5, 1.0, direction="stricter"),
            CONFIRM_PARAM()], confirm_seconds=1800),

    # --- Extended families ---
    CookbookRule(
        "SCHED-1",
        "Unoccupied runtime",
        "schedule",
        ["ahu"],
        ["occupied", "fan-status"],
        "Fan running while occupancy is unoccupied (Overview calendar → occ_mode). "
        "When zone_t is mapped, also require zone inside comfort_low…comfort_high "
        "(defaults 21.1–23.9 °C; synced from Overview zone band).",
        sched1,
        params=[
            CookbookParam("comfort_low", "Comfort low", "°C", 10.0, 26.666667, 0.277778, 21.111111),
            CookbookParam("comfort_high", "Comfort high", "°C", 12.777778, 32.222222, 0.277778, 23.888889),
            CONFIRM_PARAM(),
        ],
        optional_roles=["zone-air-temp"],
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
            "fan-status",
            "pump-status",
            "chw-pump-status",
            "hw-pump-status",
            "chiller-status",
            "compressor-status",
            "tower-fan-cmd",
            "cw-fan-cmd",
            "fan-cmd",
            "chw-pump-cmd",
            "hw-pump-cmd",
            "duct-static-pressure",
            "chw-diff-pressure",
        ],
        confirm_seconds=3600,
    ),
    CookbookRule("RESET-1", "SAT reset not tracking outdoor air", "ahu", ["ahu"],
        ["discharge-air-temp-sp", "outside-air-temp"],
        "Fan on AND |SAT SP − (11.1 + 0.25×(OAT−18.3))| > 1.7 Δ°C.",
        reset1, params=[
            CookbookParam("reset_err", "Reset error", "Δ°C", 0.277778, 5.555556, 0.277778, 1.666667),
            CookbookParam("reset_sat_at_ref", "SAT SP at the reset OAT reference", "°C", 7.222222, 18.333333, 0.277778, 11.111111),
            CookbookParam("reset_slope", "Reset slope", "Δ°C/Δ°C", 0.05, 1.0, 0.05, 0.25),
            CookbookParam("reset_oat_ref", "Reset OAT ref", "°C", 10.0, 26.666667, 0.555556, 18.333333),
            CONFIRM_PARAM()],
        optional_roles=["fan-status", "fan-cmd"], confirm_seconds=900),
    CookbookRule("CMD-1", "Fan cmd/status mismatch", "ahu", ["ahu"],
        ["fan-cmd", "fan-status"], "Fan command and proven status disagree.",
        cmd1, params=[CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("OA-1", "Low OA fraction", "ahu", ["ahu"],
        ["mixed-air-temp", "return-air-temp", "outside-air-temp", "fan-status"], "Estimated OA fraction < 15% with adequate OAT/RAT split.",
        oa1, params=[
            CookbookParam("min_oa_frac", "Min OA fraction", "frac", 0.05, 0.4, 0.01, 0.15, direction="stricter"),
            CookbookParam("oat_rat_guard", "Min |RAT−OAT| guard", "Δ°C", 0.277778, 3.333333, 0.055556, 1.222222, direction="fewer"),
            CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("DMP-1", "OA damper leakage", "ahu", ["ahu"],
        ["outside-air-temp", "mixed-air-temp", "outside-air-damper"], "Damper ≤ 5% but MAT tracks OAT within 1.1 Δ°C — leaking OA damper.",
        dmp1, params=[CookbookParam("leak_delta", "Leak ΔT", "Δ°C", 0.277778, 3.333333, 0.277778, 1.111111), CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule(
        "VLV-1",
        "Cooling valve leakage",
        "ahu",
        ["ahu"],
        ["discharge-air-temp", "discharge-air-temp-sp", "cooling-valve"],
        "Cooling valve ≤ 5% AND (SAT < sat_sp − sat_err OR SAT < MAT − mat_leak_delta). "
        "Fan proven on when fan_status/fan_cmd present (operational gate).",
        vlv1,
        params=[
            CookbookParam("sat_err", "SAT vs SP leak ΔT", "Δ°C", 0.277778, 4.444444, 0.277778, 1.111111),
            CookbookParam("mat_leak_delta", "SAT vs MAT leak ΔT", "Δ°C", 0.277778, 6.666667, 0.277778, 1.111111),
            CONFIRM_PARAM(),
        ],
        optional_roles=["mixed-air-temp", "fan-status", "fan-cmd"],
        confirm_seconds=900,
    ),
]

# Curated one-sentence summaries (explicit field — UI/DOCX/MD must not fall back to equation).
RULE_SUMMARY_OVERRIDES: dict[str, str] = {
    "SV-RANGE": "Flags any modeled sensor reading outside its physical hard range.",
    "SV-FLATLINE": "Flags a sensor that stays stuck within a tiny band for too long.",
    "SV-SPIKE": "Flags an implausible sample-to-sample jump for the sensor type.",
    "SV-STALE": "Flags when all modeled sensors stop updating — likely a dead data feed.",
    "SV-RATE": "Flags implausible sustained sensor rates of change using location- and state-aware thresholds.",
    "PID-HUNT-1": "Flags control outputs that oscillate enough to suggest loop hunting.",
    "SCHED-247": "Flags fans or pumps that stay on for nearly the entire analysis window (24/7 runtime).",
    "ECON-3": "Flags mechanical cooling during web free-cool weather when the OA damper is not fully integrated.",
    "ECON-6": "Flags an AHU economizing above min-OA when web outdoor air is below freezing (−3.9 °C).",
    "ECON-7": "Flags cooling demand during economizer-OK web weather (dew point < 15.6 °C, dry-bulb < 22.2 °C) while the OA damper is not economizing.",
    "MECH-OAT-1": "Flags proven DX or chiller cooling while web dry-bulb is below 15.6 °C.",
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
