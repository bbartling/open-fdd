"""Open-FDD Pandas cookbook — full rule catalog coded against the Haystack data model.

Every rule mirrors https://bbartling.github.io/open-fdd/rules/cookbook/pandas-cookbook.html
Rules are declarative: each carries the logical point roles it needs, plain-language
(imperial) equation text, tunable slider params, and a pure compute function that
returns a RAW boolean fault mask. The cookbook_engine resolves roles against the data
model, builds a logical frame per equipment, runs applicable rules, and confirms faults.

Fault math stays canonical (°F / in.w.c.); display unit conversion happens in the UI layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Shared helpers (mirror cookbook "Setup & shared helpers")
# ---------------------------------------------------------------------------


def norm_cmd(s: pd.Series | None) -> pd.Series:
    """Normalize a command/position 0–100 → 0–1. Passthrough if already 0–1."""
    if s is None:
        return pd.Series(dtype=float)
    s = pd.to_numeric(s, errors="coerce")
    return s.where(s <= 1.0, s / 100.0)


def as_bool(s: pd.Series | None) -> pd.Series:
    if s is None:
        return pd.Series(dtype=bool)
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().any():
        return num.fillna(0) > 0.5
    return s.fillna(False).astype(bool)


def _sv_rate_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    from app.rules.sensor_rate import sv_rate_compute

    return sv_rate_compute(d, p, poll)


# Fractional command treated as "on" for always-on screening (same as fan_on elsewhere).
SCHED247_CMD_ON_FRAC = 0.05


def _pressure_on_mask(d: pd.DataFrame, p: dict) -> pd.Series | None:
    """True when a pressure sensor shows live operating pressure (equipment likely on)."""
    thr = _f(p, "pressure_on_min", 0.20)
    for role in ("duct-static-pressure", "chw-diff-pressure", "hw-diff-pressure"):
        if role not in d.columns or not d[role].notna().any():
            continue
        s = pd.to_numeric(d[role], errors="coerce")
        return (s.notna() & (s.abs() > thr)).reindex(d.index).fillna(False)
    return None


def _sched247(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Equipment essentially always-on (fan/pump/compressor status) over the window.

    When the always-on fraction is exceeded, return the actual on-mask so fault-hours
    equal run hours (not the full analysis window). Pressure sensors (duct static /
    differential) above ``pressure_on_min`` also count as on — catches VAV systems
    where fan cmd/status mismatch but the duct is pressurized.
    """
    thr = _f(p, "always_on_pct", 0.95)
    proofs: list[pd.Series] = []
    for role in (
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
    ):
        if role not in d.columns or not d[role].notna().any():
            continue
        if role.endswith("-cmd"):
            proofs.append(norm_cmd(d[role]).fillna(0) > SCHED247_CMD_ON_FRAC)
        else:
            proofs.append(as_bool(d[role]))
    press = _pressure_on_mask(d, p)
    if press is not None:
        proofs.append(press)
    if not proofs:
        return _false(d.index)
    on = proofs[0].fillna(False).astype(bool)
    for s in proofs[1:]:
        on = on | s.fillna(False).astype(bool)
    frac = float(on.mean()) if len(on) else 0.0
    if frac >= thr:
        return on.reindex(d.index).fillna(False)
    return _false(d.index)


def _f(p: dict, key: str, default: float) -> float:
    try:
        v = p.get(key, default)
        return float(v) if v is not None else float(default)
    except (TypeError, ValueError):
        return float(default)


def _false(index) -> pd.Series:
    return pd.Series(False, index=index)


def flatline_mask(series: pd.Series, tol: float, window: int) -> pd.Series:
    window = max(2, int(window))
    roll_min = series.rolling(window, min_periods=window).min()
    roll_max = series.rolling(window, min_periods=window).max()
    return series.notna() & ((roll_max - roll_min) <= tol)


# ---------------------------------------------------------------------------
# Per-sensor validation limits (imperial primary; from sensor_fault_defaults.json)
# ---------------------------------------------------------------------------

SENSOR_LIMITS: dict[str, dict[str, float]] = {
    # role: hard low, hard high, spike per sample (°F unless noted)
    "outside-air-temp": {"lo": -60.0, "hi": 130.0, "spike": 36.0},
    "return-air-temp": {"lo": 40.0, "hi": 100.0, "spike": 12.0},
    "mixed-air-temp": {"lo": -20.0, "hi": 110.0, "spike": 25.0},
    "discharge-air-temp": {"lo": 30.0, "hi": 150.0, "spike": 40.0},
    "zone-air-temp": {"lo": 40.0, "hi": 100.0, "spike": 12.0},
    "chilled-water-supply-temp": {"lo": 30.0, "hi": 80.0, "spike": 20.0},
    "chilled-water-return-temp": {"lo": 30.0, "hi": 90.0, "spike": 20.0},
    "hot-water-supply-temp": {"lo": 40.0, "hi": 220.0, "spike": 60.0},
    "hot-water-return-temp": {"lo": 40.0, "hi": 220.0, "spike": 60.0},
    "outside-air-humidity": {"lo": 0.0, "hi": 100.0, "spike": 25.0},
    "duct-static-pressure": {"lo": -1.0, "hi": 8.0, "spike": 2.0},
}

# Sensor roles the validation sweep will check on any equipment (if present)
SWEEP_SENSOR_ROLES = list(SENSOR_LIMITS.keys())

# Flatline/stale detection targets analog temperature & humidity sensors only.
# Pressure points (e.g. duct static) legitimately rest at ~0 when equipment is off,
# so they would false-positive as "stuck" — exclude them from stuck-sensor sweeps.
_NO_FLATLINE_ROLES = {"duct-static-pressure"}
FLATLINE_SENSOR_ROLES = [r for r in SWEEP_SENSOR_ROLES if r not in _NO_FLATLINE_ROLES]


def sensor_type_for_role(role: str) -> str:
    """HVAC quantity bucket for UI grouping (Temperature / Humidity / Pressure / Flow)."""
    r = role.lower()
    if "humid" in r:
        return "Humidity"
    if "pressure" in r or "static" in r or r.endswith("-dp"):
        return "Pressure"
    if "flow" in r or "cfm" in r or "gpm" in r:
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
) -> dict:
    from app.rules.base import hours_true

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
    "mode_delay_min", "Mode-change suspension (GL36 default 30)", "min", 0.0, 60.0, 1.0, 0.0, direction="fewer"
)
FAN_ON_PARAM = lambda: CookbookParam(  # noqa: E731
    "fan_on_min", "Fan-on command threshold", "frac", 0.0, 0.25, 0.01, FAN_ON_MIN
)
EPS_TEMP_PARAM = lambda key, label, default=1.15: CookbookParam(  # noqa: E731
    key, label, "°F", 0.0, 10.0, 0.25, default, direction="fewer"
)
DELTA_TSF_PARAM = lambda: CookbookParam(  # noqa: E731
    "delta_supply_fan", "Supply-fan heat rise ΔTSF (GL36 default 2°F)", "°F", 0.0, 5.0, 0.05, DELTA_SUPPLY_FAN
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
    "mix_tol", "Legacy master sensor tolerance (sets all ε values)", "°F", 0.0, 10.0, 0.25, MIX_TOL, direction="fewer"
)
LEGACY_SUPPLY_PARAM = lambda: CookbookParam(  # noqa: E731
    "supply_tol", "Legacy SAT tolerance master (sets εSAT)", "°F", 0.0, 10.0, 0.25, SUPPLY_TOL, direction="fewer"
)


# ---------------------------------------------------------------------------
# Sensor validation sweep (SV-1/2/3 range, SV-5 stale, SV-6 flatline, SV-7 spike)
# Applied to EVERY sensor present in the data model for the equipment.
# ---------------------------------------------------------------------------


def _sweep_range(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    idx = d.index
    mask = _false(idx)
    per_role: dict[str, pd.Series] = {}
    for role in SWEEP_SENSOR_ROLES:
        if role not in d.columns:
            continue
        s = pd.to_numeric(d[role], errors="coerce")
        lim = SENSOR_LIMITS[role]
        type_scale = _role_type_scale(p, role, kind="range")
        # Widen limits when scale > 1 (more forgiving); shrink when scale < 1.
        mid = (lim["lo"] + lim["hi"]) / 2.0
        half = (lim["hi"] - lim["lo"]) / 2.0 * max(type_scale, 1e-6)
        lo, hi = mid - half, mid + half
        role_mask = s.notna() & ((s < lo) | (s > hi))
        per_role[role] = role_mask
        mask = mask | role_mask
    _stash_sweep_evidence(d, per_role, poll=poll, rule_tag="SV-RANGE")
    return mask


def _sweep_flatline(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    idx = d.index
    tol = _f(p, "flatline_tol", 0.10)
    hours = _f(p, "flatline_hours", 1.0)
    window = max(2, int(round(hours * 3600 / max(poll, 1))))
    mask = _false(idx)
    per_role: dict[str, pd.Series] = {}
    for role in FLATLINE_SENSOR_ROLES:
        if role not in d.columns:
            continue
        s = pd.to_numeric(d[role], errors="coerce")
        role_mask = flatline_mask(s, tol=tol, window=window)
        per_role[role] = role_mask
        mask = mask | role_mask
    _stash_sweep_evidence(d, per_role, poll=poll, rule_tag="SV-FLATLINE")
    return mask


def _sweep_spike(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    idx = d.index
    scale = _f(p, "spike_scale", 1.0)
    mask = _false(idx)
    per_role: dict[str, pd.Series] = {}
    for role in SWEEP_SENSOR_ROLES:
        if role not in d.columns:
            continue
        s = pd.to_numeric(d[role], errors="coerce")
        type_scale = _role_type_scale(p, role, kind="spike")
        limit = SENSOR_LIMITS[role]["spike"] * scale * type_scale
        role_mask = s.notna() & (s.diff().abs() > limit)
        per_role[role] = role_mask
        mask = mask | role_mask
    _stash_sweep_evidence(d, per_role, poll=poll, rule_tag="SV-SPIKE")
    return mask


def _sweep_stale(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Flag runs where all sweep sensors are unchanged (no fresh data)."""
    idx = d.index
    hours = _f(p, "stale_hours", 2.0)
    window = max(2, int(round(hours * 3600 / max(poll, 1))))
    present = [r for r in FLATLINE_SENSOR_ROLES if r in d.columns]
    if not present:
        _stash_sweep_evidence(d, {}, poll=poll, rule_tag="SV-STALE")
        return _false(idx)
    stale = pd.Series(True, index=idx)
    per_role: dict[str, pd.Series] = {}
    for role in present:
        s = pd.to_numeric(d[role], errors="coerce")
        role_flat = flatline_mask(s, tol=1e-9, window=window)
        per_role[role] = role_flat  # each role's stuck mask; equipment fault is AND
        stale = stale & role_flat
    # For stale, the firing evidence is the AND mask applied to each present role
    and_masks = {role: stale.copy() for role in present}
    _stash_sweep_evidence(d, and_masks, poll=poll, rule_tag="SV-STALE")
    return stale


def _pid_hunt_1(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Suspected control-output hunting across any present 0–100% analog roles."""
    from app.rules.pid_hunting import PidHuntingParams, hunting_fault_mask, iter_control_output_series

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

MIX_TOL = 1.15
SUPPLY_TOL = 1.15
AHU_MIN_OA_DPR = 0.05
DELTA_SUPPLY_FAN = 0.55
FAN_ON_MIN = 0.01


def _gl36_value(p: dict, key: str, legacy_key: str | None, default: float) -> float:
    """Read a canonical GL36 variable, retaining old session-param compatibility."""
    if key in p:
        return float(p[key])
    if legacy_key and legacy_key in p:
        return float(p[legacy_key])
    return float(default)


def _gl36_mode_stable(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """False during GL36 ModeDelay after an AHU operating-state change."""
    delay_min = _f(p, "mode_delay_min", 0.0)
    if delay_min <= 0 or d.empty:
        return pd.Series(True, index=d.index)
    htg = norm_cmd(d["heating-valve"]).fillna(0) if "heating-valve" in d else pd.Series(0.0, index=d.index)
    clg = norm_cmd(d["cooling-valve"]).fillna(0) if "cooling-valve" in d else pd.Series(0.0, index=d.index)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0) if "outside-air-damper" in d else pd.Series(0.0, index=d.index)
    fan = _fan(d)
    fan_on = _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    econ_min = _gl36_value(p, "econ_min_pos", None, AHU_MIN_OA_DPR)
    clg_on = _gl36_value(p, "clg_on_min", None, 0.01)
    htg_on = _gl36_value(p, "htg_on_min", None, 0.01)
    state = pd.Series(0, index=d.index, dtype=int)
    state[(fan > fan_on) & (htg > htg_on) & (clg <= clg_on)] = 1
    state[(fan > fan_on) & (htg <= htg_on) & (clg <= clg_on) & (econ > econ_min)] = 2
    state[(fan > fan_on) & (htg <= htg_on) & (clg > clg_on) & (econ > econ_min)] = 3
    state[(fan > fan_on) & (htg <= htg_on) & (clg > clg_on) & (econ <= econ_min)] = 4
    changed = state.ne(state.shift()).fillna(False)
    if len(changed):
        changed.iloc[0] = False
    samples = max(1, int(np.ceil(delay_min * 60.0 / max(float(poll), 1.0))))
    recent_change = changed.astype(int).rolling(samples, min_periods=1).max().astype(bool)
    return ~recent_change


def _gl36_fault(raw: pd.Series, d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    return raw.fillna(False) & _gl36_mode_stable(d, p, poll)


def _fan(d: pd.DataFrame) -> pd.Series:
    if "fan-cmd" in d.columns:
        return norm_cmd(d["fan-cmd"]).fillna(0)
    if "fan-status" in d.columns:
        return as_bool(d["fan-status"]).astype(float)
    return pd.Series(1.0, index=d.index)


def fc1(d, p, poll):
    err = _gl36_value(p, "eps_dsp", "duct_static_err", 0.12)
    speed_err = _gl36_value(p, "eps_vfd_spd", None, 0.13)
    fan_hi = _gl36_value(p, "fan_hi", None, 1.0 - speed_err)
    fan = _fan(d)
    raw = (
        d["duct-static-pressure"].notna() & d["duct-static-pressure-sp"].notna()
        & (d["duct-static-pressure"] < d["duct-static-pressure-sp"] - err)
        & (fan >= fan_hi)
    )
    return _gl36_fault(raw, d, p, poll)


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
        ts = pd.DatetimeIndex(pd.to_datetime(d["timestamp"], utc=True, errors="coerce"))
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
    oat_rat_min = _gl36_value(p, "delta_t_min", "oat_rat_delta_min", 5.0)
    design_cfm = _f(p, "min_cfm_design", 5000.0)
    fan_on = _gl36_value(p, "fan_on_min", None, FAN_ON_MIN)
    fan = _fan(d)
    rat_minus_oat = (d["return-air-temp"] - d["outside-air-temp"]).abs()
    pct_oa = ((d["mixed-air-temp"] - d["return-air-temp"]) / (d["outside-air-temp"] - d["return-air-temp"]).replace(0, np.nan)).clip(lower=0)
    perc_oamin = design_cfm / d["vav-total-airflow"].replace(0, np.nan)
    oa_err = (pct_oa - perc_oamin).abs()
    raw = (
        d["mixed-air-temp"].notna() & d["outside-air-temp"].notna() & d["return-air-temp"].notna() & d["vav-total-airflow"].notna()
        & (rat_minus_oat >= oat_rat_min) & (oa_err > airflow_err) & (fan > fan_on)
    )
    return _gl36_fault(raw, d, p, poll)


def fc7(d, p, poll):
    sat_err = _gl36_value(p, "eps_sat", "sat_err", 1.0)
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
    sat_err = _gl36_value(p, "eps_sat", "sat_err", 1.0)
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
    err = _f(p, "sat_dev_err", 5.0)
    return d["discharge-air-temp"].notna() & d["discharge-air-temp-sp"].notna() & (d["discharge-air-temp"].sub(d["discharge-air-temp-sp"]).abs() > err)


def ahu_duct_high(d, p, poll):
    """Duct static above SP + margin. Gate (not equation) decides fan-vs-pressure active window."""
    margin = _f(p, "duct_high_margin", 0.25)
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
    oat_min = _f(p, "econ1_oat_min", 55.0)
    fan = _fan(d)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    return (fan > FAN_ON_MIN) & d["outside-air-damper"].notna() & d["outside-air-temp"].notna() & (econ < 0.05) & (d["outside-air-temp"] > oat_min)


def econ2(d, p, poll):
    oat_hi = _f(p, "econ2_oat_hi", 63.0)
    dmpr = _f(p, "econ2_damper", 0.42)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    return d["outside-air-temp"].notna() & d["outside-air-damper"].notna() & (d["outside-air-temp"] > oat_hi) & (econ > dmpr)


def econ4(d, p, poll):
    oa_min_pct = _f(p, "oa_min_pct", 21.0)
    fan = _fan(d)
    oa_frac = (d["mixed-air-temp"] - d["return-air-temp"]) / (d["outside-air-temp"] - d["return-air-temp"]).replace(0, np.nan) * 100.0
    return (
        (fan > FAN_ON_MIN) & d["mixed-air-temp"].notna() & d["return-air-temp"].notna() & d["outside-air-temp"].notna()
        & ((d["return-air-temp"] - d["outside-air-temp"]).abs() > 2.2) & (oa_frac < oa_min_pct)
    )


def econ5(d, p, poll):
    over = _f(p, "preheat_over_f", 2.2)
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
        return pd.to_numeric(d["zone-airflow"], errors="coerce").fillna(0) > flow_min
    return pd.Series(True, index=d.index)


def vav1(d, p, poll):
    lo = _f(p, "zone_lo", 70.0)
    hi = _f(p, "zone_hi", 75.0)
    return d["zone-air-temp"].notna() & ((d["zone-air-temp"] < lo) | (d["zone-air-temp"] > hi))


def vav3(d, p, poll):
    oat_hi = _f(p, "reheat_oat", 78.0)
    reheat_thr = _f(p, "reheat_pct", 0.52)
    flow_min = _f(p, "flow_on_min", 25.0)
    reheat = norm_cmd(d["reheat-valve"]).fillna(0)
    return _vav_air_on(d, flow_min) & d["outside-air-temp"].notna() & (d["outside-air-temp"] > oat_hi) & (reheat > reheat_thr)


def vav4(d, p, poll):
    full_open = _f(p, "full_open_pct", 0.975)
    hours = _f(p, "sustain_hours", 1.5)
    flow_min = _f(p, "flow_on_min", 25.0)
    roll = max(2, int(round(hours * 3600 / max(poll, 1))))
    dmp = norm_cmd(d["damper"]).fillna(0)
    return (
        _vav_air_on(d, flow_min) & dmp.notna() & (dmp > full_open)
        & (dmp.rolling(roll, min_periods=roll).min() > full_open)
    )


def vav5(d, p, poll):
    dmp = norm_cmd(d["damper"]).fillna(0)
    return d["zone-airflow"].notna() & (d["zone-airflow"] > 50.0) & (dmp < 0.10)


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
    flow_min = _f(p, "flow_on_min", 25.0)
    air_on = _vav_air_on(d, flow_min)
    window = max(6, int(round(3600.0 / max(float(poll), 1.0))))
    roll_std = flow.rolling(window, min_periods=max(3, window // 2)).std()
    roll_mean = flow.rolling(window, min_periods=max(3, window // 2)).mean()
    max_std = _f(p, "fixed_flow_max_std", 15.0)
    min_mean = _f(p, "fixed_flow_min_mean", 200.0)
    fixed_high = air_on & flow.notna() & (roll_std < max_std) & (roll_mean > min_mean)
    high_min = _false(d.index)
    if "min-flow-sp" in d.columns:
        high_min_thr = _f(p, "high_min_flow_sp", 250.0)
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
    min_rise = _f(p, "min_rise", 3.0)
    flow_min = _f(p, "flow_on_min", 25.0)
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
    band = _f(p, "delta_f", 8.0)
    flow_min = _f(p, "flow_on_min", 25.0)
    leave = pd.to_numeric(d["vav-discharge-air-temp"], errors="coerce")
    ahu = pd.to_numeric(d["ahu-discharge-air-temp"], errors="coerce")
    return (
        _vav_air_on(d, flow_min)
        & leave.notna()
        & ahu.notna()
        & ((leave - ahu).abs() > band)
    )


# ---------------------------------------------------------------------------
# Central plants
# ---------------------------------------------------------------------------


def chw1(d, p, poll):
    min_dt = _f(p, "min_dt", 4.0)
    dt = d["chilled-water-return-temp"] - d["chilled-water-supply-temp"]
    if "chw-pump-cmd" in d.columns:
        pump = norm_cmd(d["chw-pump-cmd"]).fillna(0) > 0.05
    else:
        pump = pd.Series(True, index=d.index)
    return d["chilled-water-supply-temp"].notna() & d["chilled-water-return-temp"].notna() & pump & (dt < min_dt)


def chw2(d, p, poll):
    margin = _f(p, "dp_margin", 2.2)
    pmp_hi = _f(p, "pump_hi", 0.87)
    pump = norm_cmd(d["chw-pump-cmd"]).fillna(0)
    return (
        d["chw-diff-pressure"].notna() & d["chw-diff-pressure-sp"].notna()
        & (d["chw-diff-pressure"] < d["chw-diff-pressure-sp"] - margin) & (pump >= pmp_hi)
    )


def chw3(d, p, poll):
    band = _f(p, "sp_band", 2.2)
    pump = norm_cmd(d["chw-pump-cmd"]).fillna(0)
    return (
        (pump > 0.01) & d["chilled-water-supply-temp"].notna() & d["chilled-water-supply-temp-sp"].notna()
        & ((d["chilled-water-supply-temp"] < d["chilled-water-supply-temp-sp"] - band) | (d["chilled-water-supply-temp"] > d["chilled-water-supply-temp-sp"] + band))
    )


def chw4(d, p, poll):
    flow_hi = _f(p, "flow_hi", 1100.0)
    pmp_hi = _f(p, "pump_hi", 0.87)
    pump = norm_cmd(d["chw-pump-cmd"]).fillna(0)
    return d["chw-flow"].notna() & (d["chw-flow"] > flow_hi) & (pump >= pmp_hi)


# ---------------------------------------------------------------------------
# Heat pumps
# ---------------------------------------------------------------------------


def hp1(d, p, poll):
    min_sat = _f(p, "min_sat", 85.0)
    zone_cold = _f(p, "zone_cold", 69.0)
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
    spike = _f(p, "spike_limit", 16.0)
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
    approach = _f(p, "cw_approach", 7.0)
    slack = _f(p, "cw_slack", 2.0)
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


def _cw_approach_f(d: pd.DataFrame) -> pd.Series:
    """Leaving CW minus web wet-bulb (°F)."""
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
    limit = _f(p, "approach_max_f", 8.0)
    apr = _cw_approach_f(d)
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
    approach = _f(p, "cw_approach", 7.0)
    excess = _f(p, "excess_beyond_approach_f", 5.0)
    apr = _cw_approach_f(d)
    return (
        d["condenser-water-supply-temp"].notna()
        & d["web-outside-air-wetbulb"].notna()
        & _tower_fan_full_mask(d, p)
        & (apr > (approach + excess))
    )


def oat_vs_meteo(d, p, poll):
    """BAS outdoor-air sensor disagrees with Open-Meteo dry bulb by more than the threshold."""
    if "web-outside-air-temp" not in d.columns:
        return _false(d.index)
    err = _f(p, "oat_err", 5.0)
    return d["outside-air-temp"].notna() & d["web-outside-air-temp"].notna() & (d["outside-air-temp"].sub(d["web-outside-air-temp"]).abs() > err)


# ---------------------------------------------------------------------------
# Trim & respond advisory
# ---------------------------------------------------------------------------


def trim1(d, p, poll):
    duct_hi = _f(p, "duct_hi", 1.35)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["duct-static-pressure"].notna() & d["vav-pressure-request-sum"].notna()
        & (d["duct-static-pressure"] > duct_hi) & (d["vav-pressure-request-sum"] < req_lo)
    )


def trim3(d, p, poll):
    hwst_hi = _f(p, "hwst_hi", 160.0)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["hot-water-supply-temp"].notna() & d["hw-reset-request-sum"].notna()
        & (d["hot-water-supply-temp"] > hwst_hi) & (d["hw-reset-request-sum"] < req_lo)
    )


def trim4(d, p, poll):
    chw_lo = _f(p, "chw_lo", 45.0)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["chilled-water-supply-temp"].notna() & d["chw-reset-request-sum"].notna()
        & (d["chilled-water-supply-temp"] < chw_lo) & (d["chw-reset-request-sum"] < req_lo)
    )


# ---------------------------------------------------------------------------
# Extended families
# ---------------------------------------------------------------------------


def sched1(d, p, poll):
    """Unoccupied fan runtime; optional zone comfort band when zone_t is mapped."""
    if "occupied" not in d or "fan-status" not in d:
        return _false(d.index)
    base = (d["occupied"].astype(str).str.lower() == "unoccupied") & as_bool(d["fan-status"])
    if "zone-air-temp" not in d.columns or d["zone-air-temp"].notna().sum() == 0:
        return base
    lo = _f(p, "comfort_low_f", 70.0)
    hi = _f(p, "comfort_high_f", 75.0)
    zt = pd.to_numeric(d["zone-air-temp"], errors="coerce")
    in_band = zt.notna() & (zt >= lo) & (zt <= hi)
    return base & in_band


def cmd1(d, p, poll):
    cmd_on = norm_cmd(d["fan-cmd"]).fillna(0) >= 0.05
    return d["fan-status"].notna() & (cmd_on != as_bool(d["fan-status"]))


def oa1(d, p, poll):
    min_oa = _f(p, "min_oa_frac", 0.15)
    guard = _f(p, "oat_rat_guard", 2.2)
    oa_frac = (d["mixed-air-temp"] - d["return-air-temp"]) / (d["outside-air-temp"] - d["return-air-temp"]).replace(0, np.nan)
    fan = _fan(d)
    return (
        (fan > FAN_ON_MIN) & d["outside-air-temp"].notna() & d["return-air-temp"].notna() & d["mixed-air-temp"].notna()
        & ((d["return-air-temp"] - d["outside-air-temp"]).abs() > guard) & (oa_frac < min_oa)
    )


def dmp1(d, p, poll):
    leak_delta = _f(p, "leak_delta", 2.0)
    dmp = norm_cmd(d["outside-air-damper"]).fillna(0)
    return d["outside-air-temp"].notna() & d["mixed-air-temp"].notna() & (dmp <= 0.05) & (d["mixed-air-temp"].sub(d["outside-air-temp"]).abs() < leak_delta)


def vlv1(d, p, poll):
    """Cooling valve leak: valve closed AND (SAT low vs SP or SAT low vs MAT).

    Fan proven-on is enforced by the VLV-1 operational gate when fan_status/fan_cmd exist.
    """
    sat_err = _f(p, "sat_err", 2.0)
    mat_delta = _f(p, "mat_leak_delta", 2.0)
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
        ["ahu", "vav", "chiller", "boiler", "weather", "zone", "heatpump"], [],
        "Any modeled sensor reads outside its physical hard range (e.g. OAT −60–130°F, SAT 30–150°F, CHWS 30–80°F).",
        _sweep_range,
        params=[
            CookbookParam("range_scale_temperature", "Temp range scale", "x", 0.5, 2.0, 0.1, 1.0, direction="fewer"),
            CookbookParam("range_scale_humidity", "Humidity range scale", "x", 0.5, 2.0, 0.1, 1.0, direction="fewer"),
            CookbookParam("range_scale_pressure", "Pressure range scale", "x", 0.5, 2.0, 0.1, 1.0, direction="fewer"),
            CONFIRM_PARAM(),
        ],
        sensor_sweep=True,
        confirm_seconds=300,
    ),
    CookbookRule(
        "SV-FLATLINE", "Sensor flatline (stuck)", "sensor",
        ["ahu", "vav", "chiller", "boiler", "weather", "zone", "heatpump"], [],
        "Sensor value unchanged (Δ ≤ tolerance) across the flatline window — stuck / frozen sensor.",
        _sweep_flatline,
        params=[
            CookbookParam("flatline_tol", "Flatline tolerance", "°F", 0.02, 1.0, 0.02, 0.10, direction="stricter"),
            CookbookParam("flatline_hours", "Flatline window", "h", 0.5, 8.0, 0.5, 1.0, direction="fewer"),
            CONFIRM_PARAM(),
        ], sensor_sweep=True, confirm_seconds=300,
    ),
    CookbookRule(
        "SV-SPIKE", "Sensor rate-of-change spike", "sensor",
        ["ahu", "vav", "chiller", "boiler", "weather", "zone", "heatpump"], [],
        "Sample-to-sample jump exceeds the physical spike limit for the sensor type.",
        _sweep_spike, params=[
            CookbookParam("spike_scale", "Spike limit scale (global)", "x", 0.25, 3.0, 0.25, 1.0, direction="fewer"),
            CookbookParam("spike_scale_temperature", "Temp spike scale", "x", 0.25, 3.0, 0.25, 1.0, direction="fewer"),
            CookbookParam("spike_scale_humidity", "Humidity spike scale", "x", 0.25, 3.0, 0.25, 1.0, direction="fewer"),
            CookbookParam("spike_scale_pressure", "Pressure spike scale", "x", 0.25, 3.0, 0.25, 1.0, direction="fewer"),
            CONFIRM_PARAM(),
        ], sensor_sweep=True, confirm_seconds=300,
    ),
    CookbookRule(
        "SV-STALE", "Stale data (no fresh samples)", "sensor",
        ["ahu", "vav", "chiller", "boiler", "weather", "zone", "heatpump"], [],
        "All modeled sensors unchanged over the stale window — data feed likely dropped.",
        _sweep_stale, params=[
            CookbookParam("stale_hours", "Stale window", "h", 0.5, 12.0, 0.5, 2.0),
            CONFIRM_PARAM(),
        ], sensor_sweep=True, confirm_seconds=300,
    ),
    CookbookRule(
        "SV-RATE",
        "Context-aware sensor rate of change",
        "sensor",
        ["ahu", "vav", "chiller", "boiler", "weather", "zone", "heatpump"],
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
            CookbookParam("design_flow", "Design flow (flow profiles)", "cfm", 0.0, 100000.0, 100.0, 0.0),
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
            CookbookParam("eps_dsp", "Duct-static error εDSP (GL36 default 0.1 in.w.c.)", "in. w.c.", 0.0, 0.5, 0.01, 0.12),
            CookbookParam("eps_vfd_spd", "VFD speed error εVFDSPD (GL36 default 5%)", "frac", 0.0, 0.5, 0.01, 0.13),
            CookbookParam("duct_static_err", "Legacy duct-static error (sets εDSP)", "in. w.c.", 0.0, 0.5, 0.01, 0.12),
            CookbookParam("fan_hi", "Legacy fan-high threshold (sets εVFDSPD)", "frac", 0.5, 1.0, 0.01, 0.87),
            MODE_DELAY_PARAM(),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("FC2", "MAT below OAT/RAT envelope (GL36 B)", "ahu", ["ahu"],
        ["mixed-air-temp", "outside-air-temp", "return-air-temp", "fan-cmd"],
        "MATavg + εMAT < min(RATavg − εRAT, OATavg − εOAT).",
        fc2, params=[
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT (GL36 default 5°F)"),
            EPS_TEMP_PARAM("eps_rat", "RAT sensor error εRAT (GL36 default 2°F)"),
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT (GL36 default 2°F local / 5°F global)"),
            LEGACY_MIX_PARAM(), FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC3", "MAT above OAT/RAT envelope (GL36 C)", "ahu", ["ahu"],
        ["mixed-air-temp", "outside-air-temp", "return-air-temp", "fan-cmd"],
        "MATavg − εMAT > max(RATavg + εRAT, OATavg + εOAT).",
        fc3, params=[
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT (GL36 default 5°F)"),
            EPS_TEMP_PARAM("eps_rat", "RAT sensor error εRAT (GL36 default 2°F)"),
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT (GL36 default 2°F local / 5°F global)"),
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
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT (GL36 default 2°F)"),
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT (GL36 default 5°F)"),
            DELTA_TSF_PARAM(),
            CookbookParam("htg_on_min", "Heating-command ON threshold", "frac", 0.0, 0.25, 0.01, 0.01),
            LEGACY_MIX_PARAM(), FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC6", "Estimated OA fraction mismatch", "ahu", ["ahu"],
        ["mixed-air-temp", "outside-air-temp", "return-air-temp", "vav-total-airflow"],
        "|RATavg−OATavg| ≥ ΔTmin AND |estimated OA% − design min OA%| > εF.",
        fc6, params=[
            CookbookParam("eps_airflow", "Airflow error εF (GL36 default 30%)", "frac", 0.05, 1.0, 0.01, 0.15),
            CookbookParam("delta_t_min", "Minimum |OAT−RAT| ΔTmin (GL36 default 10°F)", "°F", 0.0, 30.0, 0.5, 5.0),
            CookbookParam("airflow_err", "Legacy OA-fraction error (sets εF)", "frac", 0.05, 1.0, 0.01, 0.15),
            CookbookParam("oat_rat_delta_min", "Legacy OAT/RAT guard (sets ΔTmin)", "°F", 0.0, 30.0, 0.5, 5.0),
            CookbookParam("min_cfm_design", "Design min OA CFM", "cfm", 500, 20000, 500, 5000),
            FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC7", "SAT low with full heating (GL36 E)", "ahu", ["ahu"],
        ["discharge-air-temp", "discharge-air-temp-sp", "fan-cmd", "heating-valve"],
        "SATavg < SATSP − εSAT AND HC ≥ full-heating threshold.",
        fc7, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT (GL36 default 2°F)", 1.0),
            CookbookParam("sat_err", "Legacy SAT error (sets εSAT)", "°F", 0.0, 10.0, 0.25, 1.0),
            CookbookParam("htg_full_min", "Full-heating threshold (GL36 99%)", "frac", 0.5, 1.0, 0.01, 0.90),
            FAN_ON_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC8", "SAT/MAT mismatch in economizer (GL36 F)", "ahu", ["ahu"],
        ["discharge-air-temp", "mixed-air-temp", "outside-air-damper", "cooling-valve"],
        "|SATavg − ΔTSF − MATavg| > √(εSAT² + εMAT²) in OS#2.",
        fc8, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT (GL36 default 2°F)"),
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT (GL36 default 5°F)"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), CLG_INACTIVE_PARAM(),
            LEGACY_MIX_PARAM(), LEGACY_SUPPLY_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC9", "OAT too warm for free cooling (GL36 G)", "ahu", ["ahu"],
        ["outside-air-temp", "discharge-air-temp-sp", "outside-air-damper", "cooling-valve"],
        "OATavg − εOAT > SATSP − ΔTSF + εSAT in OS#2.",
        fc9, params=[
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT (GL36 default 2°F local / 5°F global)"),
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT (GL36 default 2°F)"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), CLG_INACTIVE_PARAM(),
            LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC10", "OAT/MAT mismatch + mech cooling (GL36 H)", "ahu", ["ahu"],
        ["mixed-air-temp", "outside-air-temp", "outside-air-damper", "cooling-valve"],
        "|MATavg − OATavg| > √(εMAT² + εOAT²) in OS#3.",
        fc10, params=[
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT (GL36 default 5°F)"),
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT (GL36 default 2°F local / 5°F global)"),
            ECON_FULL_PARAM(), CLG_ON_PARAM(), LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC11", "OAT/MAT mismatch economizer-only (GL36 I)", "ahu", ["ahu"],
        ["outside-air-temp", "discharge-air-temp-sp", "outside-air-damper", "cooling-valve"],
        "OATavg + εOAT < SATSP − ΔTSF − εSAT in OS#3.",
        fc11, params=[
            EPS_TEMP_PARAM("eps_oat", "OAT sensor error εOAT (GL36 default 2°F local / 5°F global)"),
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT (GL36 default 2°F)"),
            DELTA_TSF_PARAM(), ECON_FULL_PARAM(), CLG_ON_PARAM(),
            LEGACY_MIX_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC12", "SAT above blend in cooling (GL36 J)", "ahu", ["ahu"],
        ["discharge-air-temp", "mixed-air-temp", "outside-air-damper", "cooling-valve"],
        "SATavg − εSAT − ΔTSF ≥ MATavg + εMAT in OS#3/OS#4.",
        fc12, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT (GL36 default 2°F)"),
            EPS_TEMP_PARAM("eps_mat", "MAT sensor error εMAT (GL36 default 5°F)"),
            DELTA_TSF_PARAM(), ECON_MIN_PARAM(), ECON_FULL_PARAM(), CLG_ON_PARAM(),
            LEGACY_MIX_PARAM(), LEGACY_SUPPLY_PARAM(), MODE_DELAY_PARAM(), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("FC13", "SAT above SP at full cooling (GL36 K)", "ahu", ["ahu"],
        ["discharge-air-temp", "discharge-air-temp-sp", "outside-air-damper", "cooling-valve"],
        "SATavg > SATSP + εSAT AND CC ≥ full-cooling threshold in OS#3/OS#4.",
        fc13, params=[
            EPS_TEMP_PARAM("eps_sat", "SAT sensor error εSAT (GL36 default 2°F)", 1.0),
            CookbookParam("sat_err", "Legacy SAT error (sets εSAT)", "°F", 0.0, 10.0, 0.25, 1.0),
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
        ["discharge-air-temp", "discharge-air-temp-sp"], "|SAT − SAT SP| > 5°F.",
        ahu_sat_dev, params=[CookbookParam("sat_dev_err", "SAT deviation", "°F", 1.0, 15.0, 0.5, 5.0, direction="fewer"), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("AHU-DUCTHI", "Duct static pressure high", "ahu", ["ahu"],
        ["duct-static-pressure", "duct-static-pressure-sp"],
        "Duct static > static SP + margin. Evaluates when fan is proven on OR duct static "
        "itself exceeds pressure_on_min (catches high static with fan-status off).",
        ahu_duct_high,
        params=[
            CookbookParam("duct_high_margin", "High margin", "in. w.c.", 0.05, 1.0, 0.05, 0.25, direction="fewer"),
            CookbookParam("pressure_on_min", "Pressure-on evidence", "in. w.c.", 0.05, 1.0, 0.05, 0.20, direction="stricter"),
            CONFIRM_PARAM(),
        ],
        confirm_seconds=300),
    CookbookRule("AHU-SIMUL", "Heating and cooling simultaneous", "ahu", ["ahu"],
        ["heating-valve", "cooling-valve"], "Heating valve > 10% AND cooling valve > 10% at once.",
        ahu_simul_heat_cool, params=[CookbookParam("valve_open_pct", "Valve open threshold", "frac", 0.05, 0.5, 0.01, 0.10), CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("OAT-METEO", "BAS outdoor-air sensor vs Open-Meteo", "ahu", ["ahu"],
        ["outside-air-temp", "web-outside-air-temp"], "BAS OAT sensor differs from Open-Meteo dry bulb by more than 5°F.",
        oat_vs_meteo, params=[
            CookbookParam("oat_err", "Max OAT disagreement", "°F", 2.0, 20.0, 0.5, 5.0, direction="fewer"),
            CONFIRM_PARAM()], confirm_seconds=900),

    # --- Economizer & ventilation ---
    CookbookRule("ECON-1", "Economizer stuck closed", "ahu", ["ahu"],
        ["fan-cmd", "outside-air-damper", "outside-air-temp"], "Fan on, OA damper < 5%, OAT > 55°F (should be economizing).",
        econ1, params=[CookbookParam("econ1_oat_min", "Favorable OAT", "°F", 45.0, 70.0, 1.0, 55.0), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("ECON-2", "Economizing when outdoor unfavorable", "ahu", ["ahu"],
        ["outside-air-temp", "outside-air-damper"], "OAT > 63°F AND OA damper > 42% (should be at minimum).",
        econ2, params=[
            CookbookParam("econ2_oat_hi", "OAT high cutoff", "°F", 55.0, 80.0, 1.0, 63.0),
            CookbookParam("econ2_damper", "Damper open frac", "frac", 0.2, 0.9, 0.02, 0.42),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule(
        "ECON-3",
        "Mech cooling without integrated economizer",
        "ahu",
        ["ahu"],
        ["outside-air-damper", "cooling-valve"],
        "Web free-cooling opportunity: 60°F ≤ dry-bulb < 72°F AND dewpoint < 60°F "
        "(dewpoint from web sensor or calculated from web DB+RH). Fault when cooling valve is "
        "open while OA damper is below the integrated-economizer threshold (default 90%). "
        "No BAS OAT fallback. Screenable engineering defaults — not code limits.",
        # placeholder; engine substitutes weather-aware econ3_compute
        econ2,
        params=[
            CookbookParam("econ3_db_min", "Free-cool OA dry-bulb min", "°F", 50.0, 68.0, 1.0, 60.0),
            CookbookParam("econ3_db_max", "Free-cool OA dry-bulb max", "°F", 65.0, 80.0, 1.0, 72.0),
            CookbookParam("econ3_dp_max", "Free-cool OA dew point max", "°F", 45.0, 68.0, 1.0, 60.0),
            CookbookParam("econ3_damper_hi", "Integrated economizer damper", "frac", 0.5, 1.0, 0.02, 0.90, direction="fewer"),
            CONFIRM_PARAM(),
        ],
        optional_roles=["web-outside-air-temp", "web-outside-air-dewpoint", "web-outside-air-humidity"],
        confirm_seconds=300,
    ),
    CookbookRule("ECON-4", "Low estimated OA fraction", "ahu", ["ahu"],
        ["mixed-air-temp", "return-air-temp", "outside-air-temp", "fan-cmd"], "Fan on, |RAT−OAT| > 2.2°F, estimated OA fraction < 21%.",
        econ4, params=[CookbookParam("oa_min_pct", "Min OA fraction", "%", 5.0, 40.0, 1.0, 21.0, direction="stricter"), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("ECON-5", "Preheat over-conditioning", "ahu", ["ahu"],
        ["preheat-leaving-temp", "discharge-air-temp-sp", "outside-air-temp", "heating-valve"], "Preheat leaving air > 2.2°F above target while preheat active.",
        econ5, params=[CookbookParam("preheat_over_f", "Preheat over ΔT", "°F", 0.5, 8.0, 0.1, 2.2, direction="fewer"), CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule(
        "ECON-6",
        "Economizing in freezing weather",
        "ahu",
        ["ahu"],
        ["outside-air-damper"],
        "Web dry-bulb < 25°F AND OA damper above winter min-OA ceiling (default 25%). "
        "AHU should be at minimum OA in cold weather.",
        __import__("app.rules.economizer_weather", fromlist=["econ6_compute"]).econ6_compute,
        params=[
            CookbookParam("econ6_oat_max_f", "Winter OAT ceiling", "°F", 15.0, 40.0, 1.0, 25.0),
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
        "Economizer-OK web weather: dew point < 60°F AND dry-bulb < 72°F (above a "
        "35°F freeze-guard floor; dewpoint from web sensor or calculated from web DB+RH). "
        "Fault when there is cooling demand (cooling valve open or proven DX/chiller "
        "cooling) but the OA damper stays below the economizing threshold (default 50%). "
        "Expected: economizer-only below 60°F DB (MECH-OAT-1) and mech + integrated "
        "economizer in the 60–72°F band (ECON-3). All thresholds are imperial sliders.",
        __import__("app.rules.economizer_weather", fromlist=["econ7_compute"]).econ7_compute,
        params=[
            CookbookParam("econ7_db_min", "Econ-OK dry-bulb floor (freeze guard)", "°F", 20.0, 50.0, 1.0, 35.0),
            CookbookParam("econ7_db_max", "Econ-OK dry-bulb max", "°F", 65.0, 80.0, 1.0, 72.0),
            CookbookParam("econ7_dp_max", "Econ-OK dew point max", "°F", 45.0, 68.0, 1.0, 60.0),
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
        "Mechanical cooling below 60°F web OAT",
        "ahu",
        ["ahu", "chiller", "heatpump"],
        [],
        "Proven DX/chiller mechanical cooling while web dry-bulb < 60°F. "
        "Uses compressor/chiller/pump/amps/power proof — not AHU cooling-valve alone. "
        "Below 60°F is outside the free-cool + integrated economizer band.",
        __import__("app.rules.economizer_weather", fromlist=["mech_oat1_compute"]).mech_oat1_compute,
        params=[
            CookbookParam("mech_oat_max_f", "Mech-cool OAT ceiling", "°F", 45.0, 65.0, 1.0, 60.0, direction="stricter"),
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
        __import__("app.rules.economizer_weather", fromlist=["chw_noload1_compute"]).chw_noload1_compute,
        params=[
            CookbookParam("comfort_low_f", "Comfort low", "°F", 60.0, 78.0, 0.5, 70.0),
            CookbookParam("comfort_high_f", "Comfort high", "°F", 68.0, 85.0, 0.5, 75.0),
            CookbookParam("sat_band_f", "AHU SAT≈SP band", "°F", 0.5, 6.0, 0.5, 2.0),
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

    # --- VAV zones ---
    CookbookRule("VAV-1", "Zone comfort band", "vav", ["vav", "zone"],
        ["zone-air-temp"], "Zone temp < 70°F or > 75°F.",
        vav1, params=[
            CookbookParam("zone_lo", "Zone low", "°F", 55.0, 72.0, 0.5, 70.0),
            CookbookParam("zone_hi", "Zone high", "°F", 72.0, 85.0, 0.5, 75.0),
            CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("VAV-3", "Excessive reheat during warm weather", "vav", ["vav"],
        ["outside-air-temp", "reheat-valve"], "Air flowing AND OAT > 78°F AND reheat valve > 52%.",
        vav3, params=[
            CookbookParam("reheat_oat", "Warm OAT", "°F", 65.0, 90.0, 1.0, 78.0),
            CookbookParam("reheat_pct", "Reheat frac", "frac", 0.1, 1.0, 0.02, 0.52),
            CookbookParam("flow_on_min", "Airflow-on min", "cfm", 0.0, 200.0, 5.0, 25.0),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("VAV-4", "Damper stuck at full open", "vav", ["vav"],
        ["damper"], "Air flowing AND damper > 97.5% sustained across the window.",
        vav4, params=[
            CookbookParam("full_open_pct", "Full open frac", "frac", 0.8, 1.0, 0.005, 0.975),
            CookbookParam("sustain_hours", "Sustain window", "h", 0.5, 6.0, 0.5, 1.5),
            CookbookParam("flow_on_min", "Airflow-on min", "cfm", 0.0, 200.0, 5.0, 25.0),
            CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("VAV-5", "Airflow sensor bias", "vav", ["vav"],
        ["zone-airflow", "damper"], "Airflow > 50 cfm while damper < 10% (implausible flow).",
        vav5, params=[CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("VAV-REHEAT", "Reheat valve stuck / no temp rise", "vav", ["vav"],
        ["reheat-valve", "vav-discharge-air-temp", "vav-inlet-air-temp"],
        "Air flowing AND reheat valve > 30% AND box discharge temp rises < 3°F above duct inlet "
        "(air from AHU) — stuck or failed reheat valve/coil.",
        vav_reheat_stuck, params=[
            CookbookParam("reheat_cmd", "Reheat open frac", "frac", 0.1, 1.0, 0.05, 0.30),
            CookbookParam("min_rise", "Min temp rise", "°F", 0.5, 15.0, 0.5, 3.0),
            CookbookParam("flow_on_min", "Airflow-on min", "cfm", 0.0, 200.0, 5.0, 25.0),
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
            CookbookParam("delta_f", "Leave Δ vs AHU SAT", "°F", 2.0, 25.0, 0.5, 8.0),
            CookbookParam("flow_on_min", "Airflow-on min", "cfm", 0.0, 200.0, 5.0, 25.0),
            CONFIRM_PARAM(),
        ],
        confirm_seconds=900,
    ),
    CookbookRule("VAV-7", "Min airflow / fixed high flow", "vav", ["vav"],
        ["zone-airflow"],
        "Flow below min SP (when mapped), OR airflow stays flat (low rolling std) at a high mean while air is on "
        "(mins too high / box never modulates), OR min_flow_sp itself is excessively high.",
        vav7, params=[
            CookbookParam("flow_on_min", "Airflow-on min", "cfm", 0.0, 200.0, 5.0, 25.0),
            CookbookParam("fixed_flow_max_std", "Fixed-flow max std", "cfm", 1.0, 80.0, 1.0, 15.0, direction="stricter"),
            CookbookParam("fixed_flow_min_mean", "Fixed-flow min mean", "cfm", 50.0, 2000.0, 10.0, 200.0, direction="fewer"),
            CookbookParam("high_min_flow_sp", "High min-flow SP", "cfm", 50.0, 2000.0, 10.0, 250.0, direction="fewer"),
            CONFIRM_PARAM()], confirm_seconds=900),

    # --- Central plants ---
    CookbookRule("CHW-1", "Low chilled-water ΔT", "plant", ["chiller"],
        ["chilled-water-supply-temp", "chilled-water-return-temp"], "Pump on AND (CHWR − CHWS) < 4°F.",
        chw1, params=[CookbookParam("min_dt", "Min ΔT", "°F", 1.0, 12.0, 0.5, 4.0), CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("CHW-2", "DP below SP at max pump speed", "plant", ["chiller"],
        ["chw-diff-pressure", "chw-diff-pressure-sp", "chw-pump-cmd"], "Pump ≥ 87% AND CHW DP < DP SP − 2.2.",
        chw2, params=[
            CookbookParam("dp_margin", "DP margin", "psi", 0.5, 6.0, 0.1, 2.2),
            CookbookParam("pump_hi", "Pump high-speed threshold", "frac", 0.5, 1.0, 0.01, 0.87),
            CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("CHW-3", "Plant supply temp outside deadband", "plant", ["chiller"],
        ["chilled-water-supply-temp", "chilled-water-supply-temp-sp", "chw-pump-cmd"], "Pump on AND |CHWS − CHWS SP| > 2.2°F.",
        chw3, params=[CookbookParam("sp_band", "SP band", "°F", 0.5, 6.0, 0.1, 2.2), CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("CHW-4", "Flow high at max pump", "plant", ["chiller"],
        ["chw-flow", "chw-pump-cmd"], "Pump ≥ 87% AND CHW flow > 1100 gpm.",
        chw4, params=[
            CookbookParam("flow_hi", "Flow high", "gpm", 200, 3000, 50, 1100),
            CookbookParam("pump_hi", "Pump high-speed threshold", "frac", 0.5, 1.0, 0.01, 0.87),
            CONFIRM_PARAM()], confirm_seconds=300),

    # --- Heat pumps ---
    CookbookRule("HP-1", "Discharge cold when heating", "heatpump", ["heatpump"],
        ["discharge-air-temp", "zone-air-temp", "fan-cmd"], "Fan on, zone < 69°F, discharge SAT < 85°F.",
        hp1, params=[
            CookbookParam("min_sat", "Min heating SAT", "°F", 70.0, 110.0, 1.0, 85.0, direction="stricter"),
            CookbookParam("zone_cold", "Zone cold", "°F", 60.0, 72.0, 0.5, 69.0, direction="stricter"),
            CONFIRM_PARAM()], confirm_seconds=600),

    # --- Weather / condenser ---
    CookbookRule("WX-1", "OA temperature spike", "weather", ["weather"],
        ["outside-air-temp"], "OAT sample-to-sample jump > 16°F.",
        wx1, params=[CookbookParam("spike_limit", "Spike limit", "°F", 4.0, 40.0, 1.0, 16.0), CONFIRM_PARAM()], confirm_seconds=300),
    CookbookRule("CW-OPT-1", "Condenser water not optimized vs wet-bulb", "plant", ["chiller", "cooling_tower"],
        ["condenser-water-supply-temp"],
        "CW supply significantly colder than web wet-bulb + design approach (Stull WB) — tower over-cooling / not optimized.",
        cw_opt, params=[
            CookbookParam("cw_approach", "Design approach", "°F", 3.0, 15.0, 0.5, 7.0, direction="stricter"),
            CookbookParam("cw_slack", "Slack below target", "°F", 0.5, 6.0, 0.5, 2.0, direction="fewer"),
            CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule(
        "CW-APR-1",
        "High CW approach at full tower fan",
        "plant",
        ["chiller", "cooling_tower"],
        ["condenser-water-supply-temp"],
        "At full tower fan speed, leaving CW − web wet-bulb exceeds approach_max (default 8°F, typically 5–10°F). "
        "Suspect OA→wet-bulb / CW sensor mismatch or cooling-tower performance degradation.",
        cw_apr,
        params=[
            CookbookParam("approach_max_f", "Max approach at full fan", "°F", 5.0, 15.0, 0.5, 8.0),
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
            CookbookParam("cw_approach", "Design approach", "°F", 3.0, 15.0, 0.5, 7.0),
            CookbookParam("excess_beyond_approach_f", "Excess beyond approach", "°F", 2.0, 20.0, 0.5, 5.0),
            CookbookParam("tower_fan_hi", "Tower fan full-speed threshold", "frac", 0.8, 1.0, 0.01, 0.95),
            CONFIRM_PARAM(),
        ],
        optional_roles=["tower-fan-cmd", "cw-fan-cmd", "fan-cmd", "web-outside-air-wetbulb"],
        confirm_seconds=900,
    ),

    # --- Trim & respond advisory (lumped with AHU / plants) ---
    CookbookRule("TRIM-1", "Duct static trim advisory", "trim", ["ahu"],
        ["duct-static-pressure", "vav-pressure-request-sum"], "Duct static high (> 1.35 in.w.c.) while VAV pressure requests are low.",
        trim1, params=[
            CookbookParam("duct_hi", "Duct static high", "in. w.c.", 0.5, 3.0, 0.05, 1.35, direction="fewer"),
            CookbookParam("request_lo", "Request sum low", "count", 0.0, 10.0, 0.5, 1.0, direction="stricter"),
            CONFIRM_PARAM()], confirm_seconds=1800),
    CookbookRule("TRIM-3", "HWST trim advisory", "trim", ["boiler"],
        ["hot-water-supply-temp", "hw-reset-request-sum"], "HW supply > 160°F while reset requests are low.",
        trim3, params=[
            CookbookParam("hwst_hi", "HWST high", "°F", 120.0, 200.0, 1.0, 160.0, direction="fewer"),
            CookbookParam("request_lo", "Request sum low", "count", 0.0, 10.0, 0.5, 1.0, direction="stricter"),
            CONFIRM_PARAM()], confirm_seconds=1800),
    CookbookRule("TRIM-4", "CHW plant reset advisory", "trim", ["chiller"],
        ["chilled-water-supply-temp", "chw-reset-request-sum"], "CHW supply < 45°F while reset requests are low.",
        trim4, params=[
            CookbookParam("chw_lo", "CHWS low", "°F", 35.0, 55.0, 0.5, 45.0, direction="stricter"),
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
        "When zone_t is mapped, also require zone inside comfort_low_f…comfort_high_f "
        "(defaults 70–75°F; synced from Overview zone band).",
        sched1,
        params=[
            CookbookParam("comfort_low_f", "Comfort low", "°F", 60.0, 78.0, 0.5, 70.0),
            CookbookParam("comfort_high_f", "Comfort high", "°F", 68.0, 85.0, 0.5, 75.0),
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
        "Fan or pump (or similar motor proof/command) is on for ≥ always_on_pct of the analysis "
        "window — highlights equipment that appears to run 24/7. Applies to all fans and pumps "
        "regardless of equipment family when a status/cmd role is mapped.",
        _sched247,
        params=[
            CookbookParam("always_on_pct", "Always-on fraction", "frac", 0.80, 1.0, 0.01, 0.95, direction="fewer"),
            CookbookParam(
                "pressure_on_min",
                "Pressure-on evidence",
                "eng",
                0.05,
                2.0,
                0.05,
                0.20,
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
    CookbookRule("CMD-1", "Fan cmd/status mismatch", "ahu", ["ahu"],
        ["fan-cmd", "fan-status"], "Fan command and proven status disagree.",
        cmd1, params=[CONFIRM_PARAM()], confirm_seconds=600),
    CookbookRule("OA-1", "Low OA fraction", "ahu", ["ahu"],
        ["mixed-air-temp", "return-air-temp", "outside-air-temp", "fan-status"], "Estimated OA fraction < 15% with adequate OAT/RAT split.",
        oa1, params=[
            CookbookParam("min_oa_frac", "Min OA fraction", "frac", 0.05, 0.4, 0.01, 0.15, direction="stricter"),
            CookbookParam("oat_rat_guard", "Min |RAT−OAT| guard", "°F", 0.5, 6.0, 0.1, 2.2, direction="fewer"),
            CONFIRM_PARAM()], confirm_seconds=900),
    CookbookRule("DMP-1", "OA damper leakage", "ahu", ["ahu"],
        ["outside-air-temp", "mixed-air-temp", "outside-air-damper"], "Damper ≤ 5% but MAT tracks OAT within 2°F — leaking OA damper.",
        dmp1, params=[CookbookParam("leak_delta", "Leak ΔT", "°F", 0.5, 6.0, 0.5, 2.0), CONFIRM_PARAM()], confirm_seconds=900),
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
            CookbookParam("sat_err", "SAT vs SP leak ΔT", "°F", 0.5, 8.0, 0.5, 2.0),
            CookbookParam("mat_leak_delta", "SAT vs MAT leak ΔT", "°F", 0.5, 12.0, 0.5, 2.0),
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
    "ECON-6": "Flags an AHU economizing above min-OA when web outdoor air is below freezing (25°F).",
    "ECON-7": "Flags cooling demand during economizer-OK web weather (dew point < 60°F, dry-bulb < 72°F) while the OA damper is not economizing.",
    "MECH-OAT-1": "Flags proven DX or chiller cooling while web dry-bulb is below 60°F.",
    "CHW-NOLOAD-1": "Flags a chiller running while mapped zones or AHU SAT show the building is satisfied.",
    "FC1": "Flags duct static too low while the supply fan is near full speed.",
    "FC2": "Flags mixed-air temperature colder than the OAT/RAT mixing envelope allows.",
    "FC3": "Flags mixed-air temperature warmer than the OAT/RAT mixing envelope allows.",
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
