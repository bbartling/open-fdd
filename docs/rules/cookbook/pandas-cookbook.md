---
title: Pandas cookbook
parent: Rule Cookbook
nav_order: 2
---

# Pandas FDD Cookbook

**Validated source of truth:** the Streamlit-tested vibe19 catalog (`app/rules/cookbook_catalog.py`) — **59 rules**. Open-FDD edge runs **Rust + Apache Arrow + DataFusion SQL**; this cookbook mirrors every validated rule for notebooks, CSV exports, RCx studies, and parity testing.

See also the [DataFusion SQL cookbook](datafusion-sql-cookbook.html) and [P0 rule catalog](p0-rule-catalog.html).

---

## Table of contents

1. [Setup & shared helpers](#setup--shared-helpers)
2. [Fault confirmation delay (default 5 minutes)](#fault-confirmation-delay-default-5-minutes)
3. [Sensor validation (sweep)](#sensor-validation-sweep)
4. [Control-loop hunting](#control-loop-hunting)
5. [Air handling units](#air-handling-units)
6. [VAV terminals](#vav-terminals)
7. [Central plant / condenser water](#central-plant--condenser-water)
8. [Heat pumps](#heat-pumps)
9. [Weather station](#weather-station)
10. [Trim & respond advisory](#trim--respond-advisory)
11. [Schedule & occupancy](#schedule--occupancy)
12. [Not yet in validated catalog](#not-yet-in-validated-catalog)
13. [Framework docs](#framework-docs)

---

## Setup & shared helpers

```python
import pandas as pd
import numpy as np

df = pd.read_csv("your_building_data.csv")
ts_col = "timestamp"
if ts_col in df.columns:
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=[ts_col]).sort_values(ts_col)
d = df.copy()
POLL_SECONDS = 60
```

### Normalize command 0–100 → 0–1

```python
def norm_cmd(s: pd.Series | None) -> pd.Series:
    if s is None:
        return pd.Series(dtype=float)
    s = pd.to_numeric(s, errors="coerce")
    return s.where(s <= 1.0, s / 100.0)
```

### Apply fault mask helper

```python
def apply_fault(d: pd.DataFrame, mask: pd.Series, col: str = "fault_raw") -> pd.DataFrame:
    d = d.copy()
    d[col] = mask.fillna(False)
    return d
```

### Prerequisite macros

Operational gates (fan proven-on, occupancy, override suppression) wrap many rules in the validated catalog. See [prerequisite macros](prerequisite-macros.html).

```python
def confirm_fault(raw: pd.Series, min_rows: int) -> pd.Series:
    groups = (raw != raw.shift()).cumsum()
    streak = raw.groupby(groups).cumcount() + 1
    return raw & (streak >= min_rows)
```

---

## Fault confirmation delay (default 5 minutes)

Every validated rule carries a default `confirm_seconds` (usually **300**). At 60 s poll, that is ~5 consecutive True samples — matching SQL `confirmation_seconds: 300`.

---
## Sensor validation (sweep)

Sensor-sweep rules apply to **every modeled sensor** present on the equipment (not a single fixed point).

### SV-RANGE — Sensor out of hard range
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Mode:** sensor sweep (applies to every modeled sensor present)  
**Equation:** Any modeled sensor reads outside its physical hard range (e.g. OAT −60–130°F, SAT 30–150°F, CHWS 30–80°F).  
**Default confirmation:** 300 s

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `range_scale_temperature` | Temp range scale | x | 1.0 | 0.5–2.0 |
| `range_scale_humidity` | Humidity range scale | x | 1.0 | 0.5–2.0 |
| `range_scale_pressure` | Pressure range scale | x | 1.0 | 0.5–2.0 |

```python
FAULT_CONFIRM_SECONDS = 300

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

d = apply_fault(d, _sweep_range(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### SV-FLATLINE — Sensor flatline (stuck)
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Mode:** sensor sweep (applies to every modeled sensor present)  
**Equation:** Sensor value unchanged (Δ ≤ tolerance) across the flatline window — stuck / frozen sensor.  
**Default confirmation:** 300 s

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `flatline_tol` | Flatline tolerance | °F | 0.1 | 0.02–1.0 |
| `flatline_hours` | Flatline window | h | 1.0 | 0.5–8.0 |

```python
FAULT_CONFIRM_SECONDS = 300

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

d = apply_fault(d, _sweep_flatline(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### SV-SPIKE — Sensor rate-of-change spike
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Mode:** sensor sweep (applies to every modeled sensor present)  
**Equation:** Sample-to-sample jump exceeds the physical spike limit for the sensor type.  
**Default confirmation:** 300 s

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `spike_scale` | Spike limit scale (global) | x | 1.0 | 0.25–3.0 |
| `spike_scale_temperature` | Temp spike scale | x | 1.0 | 0.25–3.0 |
| `spike_scale_humidity` | Humidity spike scale | x | 1.0 | 0.25–3.0 |
| `spike_scale_pressure` | Pressure spike scale | x | 1.0 | 0.25–3.0 |

```python
FAULT_CONFIRM_SECONDS = 300

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

d = apply_fault(d, _sweep_spike(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### SV-STALE — Stale data (no fresh samples)
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Mode:** sensor sweep (applies to every modeled sensor present)  
**Equation:** All modeled sensors unchanged over the stale window — data feed likely dropped.  
**Default confirmation:** 300 s

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `stale_hours` | Stale window | h | 2.0 | 0.5–12.0 |

```python
FAULT_CONFIRM_SECONDS = 300

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

d = apply_fault(d, _sweep_stale(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### SV-RATE — Context-aware sensor rate of change
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Mode:** sensor sweep (applies to every modeled sensor present)  
**Equation:** Implausible sustained rate-of-change for mapped sensors. Thresholds depend on quantity, location, and operating state (steady vs startup/shutdown transient). Engineering screening defaults — tune per site. Alias: SV-SLEW. Distinct from SV-SPIKE (one-sample jump), SV-RANGE, SV-FLATLINE, and PID-HUNT-1.  
**Default confirmation:** 600 s

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `persistence_min` | Fault persistence | min | 10.0 | 5.0–60.0 |
| `transition_window_min` | Transition window | min | 20.0 | 5.0–60.0 |
| `max_gap_hours` | Max sample gap | h | 2.0 | 0.25–6.0 |
| `design_flow` | Design flow (flow profiles) | cfm | 0.0 | 0.0–100000.0 |
| `sensor_span` | Sensor span (flow/pressure) | eng | 0.0 | 0.0–100000.0 |

```python
FAULT_CONFIRM_SECONDS = 600

def _sv_rate_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    from app.rules.sensor_rate import sv_rate_compute

    return sv_rate_compute(d, p, poll)

d = apply_fault(d, _sv_rate_compute(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

## Control-loop hunting

### PID-HUNT-1 — Suspected control-output hunting
**Family:** `control` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `heatpump`  
**Mode:** control-output sweep (dampers, valves, speeds, heat/cool cmds)  
**Equation:** Rolling 1h total variation of any 0–100% control output (dampers, valves, fan speeds, heat/cool cmds) with span ≥20%, TV ≥500 %·pts, ≥2.5 equivalent cycles, ≥4 reversals — suspected loop hunting (not proof of bad PID alone).  
**Default confirmation:** 0 s (rolling 1h window is its own persistence)

**Optional roles:** `loop-enabled`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `change_deadband_pct` | Ignore changes below | % out | 1.0 | 0.0–10.0 |
| `minimum_span_pct` | Minimum observed span | % out | 20.0 | 5.0–100.0 |
| `total_variation_fault_pct` | Total travel threshold | %/h | 500.0 | 50.0–2000.0 |
| `minimum_equivalent_cycles` | Min equivalent cycles | cyc/h | 2.5 | 0.5–20.0 |
| `minimum_reversals` | Min direction reversals | count | 4 | 1–40 |
| `minimum_coverage_pct` | Minimum data coverage | % | 80.0 | 25.0–100.0 |

```python
FAULT_CONFIRM_SECONDS = 0  # rolling 1h window supplies persistence

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

d = apply_fault(d, _pid_hunt_1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

## Air handling units

Includes GL36 FC1–FC15, AHU auxiliaries, economizer/ventilation, leakage, and outdoor-air screens.

### GL36 shared helpers

The FC rules read canonical GL36 epsilon variables (`eps_*`) with legacy session-param
fallbacks (`mix_tol`, `duct_static_err`, …), and suspend faulting for `mode_delay_min`
minutes after an AHU operating-state change:

```python
MIX_TOL = 1.15
SUPPLY_TOL = 1.15
AHU_MIN_OA_DPR = 0.05
DELTA_SUPPLY_FAN = 0.55
FAN_ON_MIN = 0.01

def _f(p: dict, key: str, default: float) -> float:
    try:
        v = p.get(key, default)
        return float(v) if v is not None else float(default)
    except (TypeError, ValueError):
        return float(default)

def _false(index) -> pd.Series:
    return pd.Series(False, index=index)

def _fan(d: pd.DataFrame) -> pd.Series:
    if "fan-cmd" in d.columns:
        return norm_cmd(d["fan-cmd"]).fillna(0)
    if "fan-status" in d.columns:
        return as_bool(d["fan-status"]).astype(float)
    return pd.Series(1.0, index=d.index)

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
```

### FC1 — Duct static below SP at full fan (GL36 A)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** DSP < DSPSP − εDSP AND VFDSPD ≥ 100% − εVFDSPD.  
**Default confirmation:** 300 s

**Required roles:** `duct-static-pressure`, `duct-static-pressure-sp`, `fan-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_dsp` | Duct-static error εDSP (GL36 default 0.1 in.w.c.) | in. w.c. | 0.12 | 0.0–0.5 |
| `eps_vfd_spd` | VFD speed error εVFDSPD (GL36 default 5%) | frac | 0.13 | 0.0–0.5 |
| `duct_static_err` | Legacy duct-static error (sets εDSP) | in. w.c. | 0.12 | 0.0–0.5 |
| `fan_hi` | Legacy fan-high threshold (sets εVFDSPD) | frac | 0.87 | 0.5–1.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 300

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

d = apply_fault(d, fc1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC2 — MAT below OAT/RAT envelope (GL36 B)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** MATavg + εMAT < min(RATavg − εRAT, OATavg − εOAT).  
**Default confirmation:** 600 s

**Required roles:** `mixed-air-temp`, `outside-air-temp`, `return-air-temp`, `fan-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `eps_rat` | RAT sensor error εRAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `eps_oat` | OAT sensor error εOAT (GL36 default 2°F local / 5°F global) | °F | 1.15 | 0.0–10.0 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `fan_on_min` | Fan-on command threshold | frac | 0.01 | 0.0–0.25 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc2(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC3 — MAT above OAT/RAT envelope (GL36 C)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** MATavg − εMAT > max(RATavg + εRAT, OATavg + εOAT).  
**Default confirmation:** 600 s

**Required roles:** `mixed-air-temp`, `outside-air-temp`, `return-air-temp`, `fan-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `eps_rat` | RAT sensor error εRAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `eps_oat` | OAT sensor error εOAT (GL36 default 2°F local / 5°F global) | °F | 1.15 | 0.0–10.0 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `fan_on_min` | Fan-on command threshold | frac | 0.01 | 0.0–0.25 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc3(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC4 — PID hunting (operating-state oscillation)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** ΔOS > ΔOSmax during the prior 60-minute moving window.  
**Default confirmation:** 3600 s

**Required roles:** `outside-air-damper`, `cooling-valve`, `fan-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `delta_os_max` | Max mode changes/hr ΔOSmax (GL36 default 7) | count | 5 | 1–30 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 3600

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

d = apply_fault(d, fc4(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC5 — SAT cold when heating commanded (GL36 D)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** SATavg + εSAT ≤ MATavg − εMAT + ΔTSF while heating is commanded.  
**Default confirmation:** 600 s

**Required roles:** `discharge-air-temp`, `mixed-air-temp`, `fan-cmd`, `heating-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `htg_on_min` | Heating-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `fan_on_min` | Fan-on command threshold | frac | 0.01 | 0.0–0.25 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc5(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC6 — Estimated OA fraction mismatch
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** |RATavg−OATavg| ≥ ΔTmin AND |estimated OA% − design min OA%| > εF.  
**Default confirmation:** 600 s

**Required roles:** `mixed-air-temp`, `outside-air-temp`, `return-air-temp`, `vav-total-airflow`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_airflow` | Airflow error εF (GL36 default 30%) | frac | 0.15 | 0.05–1.0 |
| `delta_t_min` | Minimum |OAT−RAT| ΔTmin (GL36 default 10°F) | °F | 5.0 | 0.0–30.0 |
| `airflow_err` | Legacy OA-fraction error (sets εF) | frac | 0.15 | 0.05–1.0 |
| `oat_rat_delta_min` | Legacy OAT/RAT guard (sets ΔTmin) | °F | 5.0 | 0.0–30.0 |
| `min_cfm_design` | Design min OA CFM | cfm | 5000 | 500–20000 |
| `fan_on_min` | Fan-on command threshold | frac | 0.01 | 0.0–0.25 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc6(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC7 — SAT low with full heating (GL36 E)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** SATavg < SATSP − εSAT AND HC ≥ full-heating threshold.  
**Default confirmation:** 600 s

**Required roles:** `discharge-air-temp`, `discharge-air-temp-sp`, `fan-cmd`, `heating-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.0 | 0.0–10.0 |
| `sat_err` | Legacy SAT error (sets εSAT) | °F | 1.0 | 0.0–10.0 |
| `htg_full_min` | Full-heating threshold (GL36 99%) | frac | 0.9 | 0.5–1.0 |
| `fan_on_min` | Fan-on command threshold | frac | 0.01 | 0.0–0.25 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc7(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC8 — SAT/MAT mismatch in economizer (GL36 F)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** |SATavg − ΔTSF − MATavg| > √(εSAT² + εMAT²) in OS#2.  
**Default confirmation:** 600 s

**Required roles:** `discharge-air-temp`, `mixed-air-temp`, `outside-air-damper`, `cooling-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `clg_inactive_max` | Cooling-command inactive ceiling | frac | 0.1 | 0.0–0.5 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `supply_tol` | Legacy SAT tolerance master (sets εSAT) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc8(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC9 — OAT too warm for free cooling (GL36 G)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** OATavg − εOAT > SATSP − ΔTSF + εSAT in OS#2.  
**Default confirmation:** 600 s

**Required roles:** `outside-air-temp`, `discharge-air-temp-sp`, `outside-air-damper`, `cooling-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_oat` | OAT sensor error εOAT (GL36 default 2°F local / 5°F global) | °F | 1.15 | 0.0–10.0 |
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `clg_inactive_max` | Cooling-command inactive ceiling | frac | 0.1 | 0.0–0.5 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc9(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC10 — OAT/MAT mismatch + mech cooling (GL36 H)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** |MATavg − OATavg| > √(εMAT² + εOAT²) in OS#3.  
**Default confirmation:** 600 s

**Required roles:** `mixed-air-temp`, `outside-air-temp`, `outside-air-damper`, `cooling-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `eps_oat` | OAT sensor error εOAT (GL36 default 2°F local / 5°F global) | °F | 1.15 | 0.0–10.0 |
| `econ_full_open` | Economizer full-open threshold | frac | 0.9 | 0.5–1.0 |
| `clg_on_min` | Cooling-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc10(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC11 — OAT/MAT mismatch economizer-only (GL36 I)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** OATavg + εOAT < SATSP − ΔTSF − εSAT in OS#3.  
**Default confirmation:** 600 s

**Required roles:** `outside-air-temp`, `discharge-air-temp-sp`, `outside-air-damper`, `cooling-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_oat` | OAT sensor error εOAT (GL36 default 2°F local / 5°F global) | °F | 1.15 | 0.0–10.0 |
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_full_open` | Economizer full-open threshold | frac | 0.9 | 0.5–1.0 |
| `clg_on_min` | Cooling-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc11(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC12 — SAT above blend in cooling (GL36 J)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** SATavg − εSAT − ΔTSF ≥ MATavg + εMAT in OS#3/OS#4.  
**Default confirmation:** 600 s

**Required roles:** `discharge-air-temp`, `mixed-air-temp`, `outside-air-damper`, `cooling-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `econ_full_open` | Economizer full-open threshold | frac | 0.9 | 0.5–1.0 |
| `clg_on_min` | Cooling-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `supply_tol` | Legacy SAT tolerance master (sets εSAT) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc12(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC13 — SAT above SP at full cooling (GL36 K)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** SATavg > SATSP + εSAT AND CC ≥ full-cooling threshold in OS#3/OS#4.  
**Default confirmation:** 600 s

**Required roles:** `discharge-air-temp`, `discharge-air-temp-sp`, `outside-air-damper`, `cooling-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.0 | 0.0–10.0 |
| `sat_err` | Legacy SAT error (sets εSAT) | °F | 1.0 | 0.0–10.0 |
| `clg_full_min` | Full-cooling threshold (GL36 99%) | frac | 0.01 | 0.5–1.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `econ_full_open` | Economizer full-open threshold | frac | 0.9 | 0.5–1.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc13(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC14 — CHW coil ΔT when inactive (GL36 L)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Cooling-coil ΔT ≥ √(εCCET² + εCCLT²) + ΔTSF while coil should be inactive.  
**Default confirmation:** 600 s

**Required roles:** `cooling-coil-entering-temp`, `cooling-coil-leaving-temp`, `outside-air-damper`, `cooling-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_ccet` | Cooling-coil entering sensor error εCCET | °F | 1.15 | 0.0–10.0 |
| `eps_cclt` | Cooling-coil leaving sensor error εCCLT | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `clg_inactive_max` | Cooling-command inactive ceiling | frac | 0.1 | 0.0–0.5 |
| `htg_on_min` | Heating-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc14(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### FC15 — HW coil ΔT when inactive (GL36 M)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Heating-coil ΔT ≥ √(εHCET² + εHCLT²) + ΔTSF while coil should be inactive.  
**Default confirmation:** 600 s

**Required roles:** `heating-coil-entering-temp`, `heating-coil-leaving-temp`, `outside-air-damper`, `cooling-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_hcet` | Heating-coil entering sensor error εHCET | °F | 1.15 | 0.0–10.0 |
| `eps_hclt` | Heating-coil leaving sensor error εHCLT | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `econ_full_open` | Economizer full-open threshold | frac | 0.9 | 0.5–1.0 |
| `clg_inactive_max` | Cooling-command inactive ceiling | frac | 0.1 | 0.0–0.5 |
| `clg_on_min` | Cooling-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, fc15(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### AHU-SATDEV — SAT deviation from setpoint
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** abs(SAT − SAT SP) > 5°F.  
**Default confirmation:** 600 s

**Required roles:** `discharge-air-temp`, `discharge-air-temp-sp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `sat_dev_err` | SAT deviation | °F | 5.0 | 1.0–15.0 |

```python
FAULT_CONFIRM_SECONDS = 600

def ahu_sat_dev(d, p, poll):
    err = _f(p, "sat_dev_err", 5.0)
    return d["discharge-air-temp"].notna() & d["discharge-air-temp-sp"].notna() & (d["discharge-air-temp"].sub(d["discharge-air-temp-sp"]).abs() > err)

d = apply_fault(d, ahu_sat_dev(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### AHU-DUCTHI — Duct static pressure high
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Duct static > static SP + margin. Evaluates when fan is proven on OR duct static itself exceeds pressure_on_min (catches high static with fan-status off).  
**Default confirmation:** 300 s

**Required roles:** `duct-static-pressure`, `duct-static-pressure-sp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `duct_high_margin` | High margin | in. w.c. | 0.25 | 0.05–1.0 |
| `pressure_on_min` | Pressure-on evidence | in. w.c. | 0.2 | 0.05–1.0 |

```python
FAULT_CONFIRM_SECONDS = 300

def ahu_duct_high(d, p, poll):
    """Duct static above SP + margin. Gate (not equation) decides fan-vs-pressure active window."""
    margin = _f(p, "duct_high_margin", 0.25)
    return (
        d["duct-static-pressure"].notna()
        & d["duct-static-pressure-sp"].notna()
        & (d["duct-static-pressure"] > d["duct-static-pressure-sp"] + margin)
    )

d = apply_fault(d, ahu_duct_high(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### AHU-SIMUL — Heating and cooling simultaneous
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Heating valve > 10% AND cooling valve > 10% at once.  
**Default confirmation:** 300 s

**Required roles:** `heating-valve`, `cooling-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `valve_open_pct` | Valve open threshold | frac | 0.1 | 0.05–0.5 |

```python
FAULT_CONFIRM_SECONDS = 300

def ahu_simul_heat_cool(d, p, poll):
    thr = _f(p, "valve_open_pct", 0.10)
    htg = norm_cmd(d["heating-valve"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    return (htg > thr) & (clg > thr)

d = apply_fault(d, ahu_simul_heat_cool(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### OAT-METEO — BAS outdoor-air sensor vs Open-Meteo
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** BAS OAT sensor differs from Open-Meteo dry bulb by more than 5°F.  
**Default confirmation:** 900 s

**Required roles:** `outside-air-temp`, `web-outside-air-temp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `oat_err` | Max OAT disagreement | °F | 5.0 | 2.0–20.0 |

```python
FAULT_CONFIRM_SECONDS = 900

def oat_vs_meteo(d, p, poll):
    """BAS outdoor-air sensor disagrees with Open-Meteo dry bulb by more than the threshold."""
    if "web-outside-air-temp" not in d.columns:
        return _false(d.index)
    err = _f(p, "oat_err", 5.0)
    return d["outside-air-temp"].notna() & d["web-outside-air-temp"].notna() & (d["outside-air-temp"].sub(d["web-outside-air-temp"]).abs() > err)

d = apply_fault(d, oat_vs_meteo(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### ECON-1 — Economizer stuck closed
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Fan on, OA damper < 5%, OAT > 55°F (should be economizing).  
**Default confirmation:** 600 s

**Required roles:** `fan-cmd`, `outside-air-damper`, `outside-air-temp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `econ1_oat_min` | Favorable OAT | °F | 55.0 | 45.0–70.0 |

```python
FAULT_CONFIRM_SECONDS = 600

def econ1(d, p, poll):
    oat_min = _f(p, "econ1_oat_min", 55.0)
    fan = _fan(d)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    return (fan > FAN_ON_MIN) & d["outside-air-damper"].notna() & d["outside-air-temp"].notna() & (econ < 0.05) & (d["outside-air-temp"] > oat_min)

d = apply_fault(d, econ1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### ECON-2 — Economizing when outdoor unfavorable
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** OAT > 63°F AND OA damper > 42% (should be at minimum).  
**Default confirmation:** 300 s

**Required roles:** `outside-air-temp`, `outside-air-damper`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `econ2_oat_hi` | OAT high cutoff | °F | 63.0 | 55.0–80.0 |
| `econ2_damper` | Damper open frac | frac | 0.42 | 0.2–0.9 |

```python
FAULT_CONFIRM_SECONDS = 300

def econ2(d, p, poll):
    oat_hi = _f(p, "econ2_oat_hi", 63.0)
    dmpr = _f(p, "econ2_damper", 0.42)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    return d["outside-air-temp"].notna() & d["outside-air-damper"].notna() & (d["outside-air-temp"] > oat_hi) & (econ > dmpr)

d = apply_fault(d, econ2(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### ECON-3 — Mech cooling without integrated economizer
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Web free-cooling opportunity: 60°F ≤ dry-bulb < 72°F AND dewpoint < 60°F (dewpoint from web sensor or calculated from web DB+RH). Fault when cooling valve is open while OA damper is below the integrated-economizer threshold (default 90%). No BAS OAT fallback. Screenable engineering defaults — not code limits.  
**Default confirmation:** 300 s

**Required roles:** `outside-air-damper`, `cooling-valve` (plus web OAT/RH or dewpoint columns)

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `econ3_db_min` | Free-cool OA dry-bulb min | °F | 60.0 | 50.0–68.0 |
| `econ3_db_max` | Free-cool OA dry-bulb max | °F | 72.0 | 65.0–80.0 |
| `econ3_dp_max` | Free-cool OA dew point max | °F | 60.0 | 45.0–68.0 |
| `econ3_damper_hi` | Integrated economizer damper | frac | 0.9 | 0.5–1.0 |

```python
FAULT_CONFIRM_SECONDS = 300

# Validated compute lives in economizer_weather.econ3_compute
# (catalog entry uses a placeholder; the Streamlit engine substitutes this function).
def econ3_compute(d: pd.DataFrame, p: dict, poll: float, wx_ok: bool = True) -> pd.Series:
    """Fault: mech cooling while free cooling available but OA damper not integrated-open.

    Weather: strict web dry-bulb + dewpoint (calculated from web RH if needed).
    Band: 60 ≤ DB < 72°F and DP < 60°F. Damper must be ≥ integrated threshold (default 90%).
    """
    del wx_ok  # web presence is resolved explicitly below
    if not {"outside-air-damper", "cooling-valve"}.issubset(d.columns):
        return _false(d.index)
    db, dp, src = resolve_web_drybulb_dewpoint(d)
    if db is None or dp is None:
        d.attrs["econ3_weather_source"] = src
        return _false(d.index)

    db_min = _f(p, "econ3_db_min", 60.0)
    db_max = _f(p, "econ3_db_max", 72.0)
    dp_max = _f(p, "econ3_dp_max", 60.0)
    damper_hi = _f(p, "econ3_damper_hi", 0.90)

    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    opportunity = free_cool_opportunity_mask(db, dp, db_min=db_min, db_max=db_max, dp_max=dp_max)
    mech = clg > 0.01
    not_integrated = econ < damper_hi
    raw = opportunity & mech & not_integrated
    d.attrs["econ3_weather_source"] = src
    return raw.fillna(False)

d = apply_fault(d, econ3_compute(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```


### ECON-4 — Low estimated OA fraction
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Fan on, abs(RAT−OAT) > 2.2°F, estimated OA fraction < 21%.  
**Default confirmation:** 600 s

**Required roles:** `mixed-air-temp`, `return-air-temp`, `outside-air-temp`, `fan-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `oa_min_pct` | Min OA fraction | % | 21.0 | 5.0–40.0 |

```python
FAULT_CONFIRM_SECONDS = 600

def econ4(d, p, poll):
    oa_min_pct = _f(p, "oa_min_pct", 21.0)
    fan = _fan(d)
    oa_frac = (d["mixed-air-temp"] - d["return-air-temp"]) / (d["outside-air-temp"] - d["return-air-temp"]).replace(0, np.nan) * 100.0
    return (
        (fan > FAN_ON_MIN) & d["mixed-air-temp"].notna() & d["return-air-temp"].notna() & d["outside-air-temp"].notna()
        & ((d["return-air-temp"] - d["outside-air-temp"]).abs() > 2.2) & (oa_frac < oa_min_pct)
    )

d = apply_fault(d, econ4(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### ECON-5 — Preheat over-conditioning
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Preheat leaving air > 2.2°F above target while preheat active.  
**Default confirmation:** 600 s

**Required roles:** `preheat-leaving-temp`, `discharge-air-temp-sp`, `outside-air-temp`, `heating-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `preheat_over_f` | Preheat over ΔT | °F | 2.2 | 0.5–8.0 |

```python
FAULT_CONFIRM_SECONDS = 600

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

d = apply_fault(d, econ5(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### ECON-6 — Economizing in freezing weather
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Web dry-bulb < 25°F AND OA damper above winter min-OA ceiling (default 25%). AHU should be at minimum OA in cold weather.  
**Default confirmation:** 600 s

**Required roles:** `outside-air-damper`

**Optional roles:** `web-outside-air-temp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `econ6_oat_max_f` | Winter OAT ceiling | °F | 25.0 | 15.0–40.0 |
| `econ6_damper_max` | Winter min-OA damper | frac | 0.25 | 0.05–0.5 |

```python
FAULT_CONFIRM_SECONDS = 600

def econ6_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Fault: OA damper above winter min-OA ceiling while web OAT < 25°F."""
    del poll
    if "outside-air-damper" not in d.columns:
        return _false(d.index)
    db, _dp, src = resolve_web_drybulb_dewpoint(d)
    d.attrs["econ6_weather_source"] = src
    if db is None:
        return _false(d.index)
    oat_max = _f(p, "econ6_oat_max_f", 25.0)
    damper_max = _f(p, "econ6_damper_max", 0.25)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    return (db.notna() & (db < oat_max) & (econ > damper_max)).fillna(False)

d = apply_fault(d, econ6_compute(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### ECON-7 — Economizer OK but not economizing
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Economizer-OK web weather: dew point < 60°F AND dry-bulb < 72°F (above a 35°F freeze-guard floor; dewpoint from web sensor or calculated from web DB+RH). Fault when there is cooling demand (cooling valve open or proven DX/chiller cooling) but the OA damper stays below the economizing threshold (default 50%). Expected: economizer-only below 60°F DB (MECH-OAT-1) and mech + integrated economizer in the 60–72°F band (ECON-3). All thresholds are imperial sliders.  
**Default confirmation:** 600 s

**Required roles:** `outside-air-damper`

**Optional roles:** `web-outside-air-temp`, `web-outside-air-dewpoint`, `web-outside-air-humidity`, `cooling-valve`, `compressor-status`, `dx-cool-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `econ7_db_min` | Econ-OK dry-bulb floor (freeze guard) | °F | 35.0 | 20.0–50.0 |
| `econ7_db_max` | Econ-OK dry-bulb max | °F | 72.0 | 65.0–80.0 |
| `econ7_dp_max` | Econ-OK dew point max | °F | 60.0 | 45.0–68.0 |
| `econ7_damper_min` | Economizing damper threshold | frac | 0.5 | 0.2–0.9 |

```python
FAULT_CONFIRM_SECONDS = 600

def econ7_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Fault: economizer-OK web weather with cooling demand, but OA damper not economizing.

    Economizer OK: web dew point < 60°F AND dry-bulb < 72°F (above a freeze-guard
    floor, default 35°F). Dewpoint comes from the web sensor or is calculated from
    web DB+RH. Cooling demand: cooling valve open OR proven DX/chiller cooling.
    Expected operation: economizer-only below 60°F DB (see MECH-OAT-1) and
    mech + integrated economizer in the 60–72°F band (see ECON-3).
    """
    del poll
    if "outside-air-damper" not in d.columns:
        return _false(d.index)
    db, dp, src = resolve_web_drybulb_dewpoint(d)
    d.attrs["econ7_weather_source"] = src
    if db is None or dp is None:
        return _false(d.index)

    db_min = _f(p, "econ7_db_min", 35.0)
    db_max = _f(p, "econ7_db_max", 72.0)
    dp_max = _f(p, "econ7_dp_max", 60.0)
    damper_min = _f(p, "econ7_damper_min", 0.50)

    econ_ok = free_cool_opportunity_mask(db, dp, db_min=db_min, db_max=db_max, dp_max=dp_max)

    demand = _false(d.index)
    has_demand_signal = False
    if "cooling-valve" in d.columns and d["cooling-valve"].notna().any():
        demand = demand | (norm_cmd(d["cooling-valve"]).fillna(0) > 0.05)
        has_demand_signal = True
    mech, kind = mechanical_proof_mask(d)
    d.attrs["econ7_proof"] = kind
    if kind:
        demand = demand | mech
        has_demand_signal = True
    if not has_demand_signal:
        d.attrs["econ7_skip"] = "missing_cooling_demand_signal"
        return _false(d.index)

    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    return (econ_ok & demand & (econ < damper_min)).fillna(False)

d = apply_fault(d, econ7_compute(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### MECH-OAT-1 — Mechanical cooling below 60°F web OAT
**Family:** `ahu` · **Equipment:** `ahu`, `chiller`, `heatpump`  
**Equation:** Proven DX/chiller mechanical cooling while web dry-bulb < 60°F. Uses compressor/chiller/pump/amps/power proof — not AHU cooling-valve alone. Below 60°F is outside the free-cool + integrated economizer band.  
**Default confirmation:** 600 s

**Optional roles:** `web-outside-air-temp`, `compressor-status`, `chiller-status`, `chw-pump-status`, `dx-cool-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `mech_oat_max_f` | Mech-cool OAT ceiling | °F | 60.0 | 45.0–65.0 |

```python
FAULT_CONFIRM_SECONDS = 600

def mech_oat1_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Fault: proven mechanical cooling while web dry-bulb < 60°F."""
    del poll
    db, _dp, src = resolve_web_drybulb_dewpoint(d)
    d.attrs["mech_oat1_weather_source"] = src
    if db is None:
        return _false(d.index)
    oat_max = _f(p, "mech_oat_max_f", 60.0)
    run, kind = mechanical_proof_mask(d)
    d.attrs["mech_oat1_proof"] = kind
    if not kind:
        return _false(d.index)
    return (db.notna() & (db < oat_max) & run).fillna(False)

d = apply_fault(d, mech_oat1_compute(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### CMD-1 — Fan cmd/status mismatch
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Fan command and proven status disagree.  
**Default confirmation:** 600 s

**Required roles:** `fan-cmd`, `fan-status`

**Tunable params**

_No tunable thresholds beyond confirmation delay._

```python
FAULT_CONFIRM_SECONDS = 600

def cmd1(d, p, poll):
    cmd_on = norm_cmd(d["fan-cmd"]).fillna(0) >= 0.05
    return d["fan-status"].notna() & (cmd_on != as_bool(d["fan-status"]))

d = apply_fault(d, cmd1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### OA-1 — Low OA fraction
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Estimated OA fraction < 15% with adequate OAT/RAT split.  
**Default confirmation:** 900 s

**Required roles:** `mixed-air-temp`, `return-air-temp`, `outside-air-temp`, `fan-status`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `min_oa_frac` | Min OA fraction | frac | 0.15 | 0.05–0.4 |
| `oat_rat_guard` | Min abs(RAT−OAT) guard | °F | 2.2 | 0.5–6.0 |

```python
FAULT_CONFIRM_SECONDS = 900

def oa1(d, p, poll):
    min_oa = _f(p, "min_oa_frac", 0.15)
    guard = _f(p, "oat_rat_guard", 2.2)
    oa_frac = (d["mixed-air-temp"] - d["return-air-temp"]) / (d["outside-air-temp"] - d["return-air-temp"]).replace(0, np.nan)
    fan = _fan(d)
    return (
        (fan > FAN_ON_MIN) & d["outside-air-temp"].notna() & d["return-air-temp"].notna() & d["mixed-air-temp"].notna()
        & ((d["return-air-temp"] - d["outside-air-temp"]).abs() > guard) & (oa_frac < min_oa)
    )

d = apply_fault(d, oa1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### DMP-1 — OA damper leakage
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Damper ≤ 5% but MAT tracks OAT within 2°F — leaking OA damper.  
**Default confirmation:** 900 s

**Required roles:** `outside-air-temp`, `mixed-air-temp`, `outside-air-damper`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `leak_delta` | Leak ΔT | °F | 2.0 | 0.5–6.0 |

```python
FAULT_CONFIRM_SECONDS = 900

def dmp1(d, p, poll):
    leak_delta = _f(p, "leak_delta", 2.0)
    dmp = norm_cmd(d["outside-air-damper"]).fillna(0)
    return d["outside-air-temp"].notna() & d["mixed-air-temp"].notna() & (dmp <= 0.05) & (d["mixed-air-temp"].sub(d["outside-air-temp"]).abs() < leak_delta)

d = apply_fault(d, dmp1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### VLV-1 — Cooling valve leakage
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Cooling valve ≤ 5% AND (SAT < sat_sp − sat_err OR SAT < MAT − mat_leak_delta). Fan proven on when fan_status/fan_cmd present (operational gate).  
**Default confirmation:** 900 s

**Required roles:** `discharge-air-temp`, `discharge-air-temp-sp`, `cooling-valve`

**Optional roles:** `mixed-air-temp`, `fan-status`, `fan-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `sat_err` | SAT vs SP leak ΔT | °F | 2.0 | 0.5–8.0 |
| `mat_leak_delta` | SAT vs MAT leak ΔT | °F | 2.0 | 0.5–12.0 |

```python
FAULT_CONFIRM_SECONDS = 900

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

d = apply_fault(d, vlv1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

## VAV terminals

### VAV-1 — Zone comfort band
**Family:** `vav` · **Equipment:** `vav`, `zone`  
**Equation:** Zone temp < 70°F or > 75°F.  
**Default confirmation:** 900 s

**Required roles:** `zone-air-temp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `zone_lo` | Zone low | °F | 70.0 | 55.0–72.0 |
| `zone_hi` | Zone high | °F | 75.0 | 72.0–85.0 |

```python
FAULT_CONFIRM_SECONDS = 900

def vav1(d, p, poll):
    lo = _f(p, "zone_lo", 70.0)
    hi = _f(p, "zone_hi", 75.0)
    return d["zone-air-temp"].notna() & ((d["zone-air-temp"] < lo) | (d["zone-air-temp"] > hi))

d = apply_fault(d, vav1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### VAV-3 — Excessive reheat during warm weather
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Air flowing AND OAT > 78°F AND reheat valve > 52%.  
**Default confirmation:** 300 s

**Required roles:** `outside-air-temp`, `reheat-valve`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `reheat_oat` | Warm OAT | °F | 78.0 | 65.0–90.0 |
| `reheat_pct` | Reheat frac | frac | 0.52 | 0.1–1.0 |
| `flow_on_min` | Airflow-on min | cfm | 25.0 | 0.0–200.0 |

```python
FAULT_CONFIRM_SECONDS = 300

def vav3(d, p, poll):
    oat_hi = _f(p, "reheat_oat", 78.0)
    reheat_thr = _f(p, "reheat_pct", 0.52)
    flow_min = _f(p, "flow_on_min", 25.0)
    reheat = norm_cmd(d["reheat-valve"]).fillna(0)
    return _vav_air_on(d, flow_min) & d["outside-air-temp"].notna() & (d["outside-air-temp"] > oat_hi) & (reheat > reheat_thr)

d = apply_fault(d, vav3(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### VAV-4 — Damper stuck at full open
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Air flowing AND damper > 97.5% sustained across the window.  
**Default confirmation:** 900 s

**Required roles:** `damper`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `full_open_pct` | Full open frac | frac | 0.975 | 0.8–1.0 |
| `sustain_hours` | Sustain window | h | 1.5 | 0.5–6.0 |
| `flow_on_min` | Airflow-on min | cfm | 25.0 | 0.0–200.0 |

```python
FAULT_CONFIRM_SECONDS = 900

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

d = apply_fault(d, vav4(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### VAV-5 — Airflow sensor bias
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Airflow > 50 cfm while damper < 10% (implausible flow).  
**Default confirmation:** 900 s

**Required roles:** `zone-airflow`, `damper`

**Tunable params**

_No tunable thresholds beyond confirmation delay._

```python
FAULT_CONFIRM_SECONDS = 900

def vav5(d, p, poll):
    dmp = norm_cmd(d["damper"]).fillna(0)
    return d["zone-airflow"].notna() & (d["zone-airflow"] > 50.0) & (dmp < 0.10)

d = apply_fault(d, vav5(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### VAV-REHEAT — Reheat valve stuck / no temp rise
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Air flowing AND reheat valve > 30% AND box discharge temp rises < 3°F above duct inlet (air from AHU) — stuck or failed reheat valve/coil.  
**Default confirmation:** 900 s

**Required roles:** `reheat-valve`, `vav-discharge-air-temp`, `vav-inlet-air-temp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `reheat_cmd` | Reheat open frac | frac | 0.3 | 0.1–1.0 |
| `min_rise` | Min temp rise | °F | 3.0 | 0.5–15.0 |
| `flow_on_min` | Airflow-on min | cfm | 25.0 | 0.0–200.0 |

```python
FAULT_CONFIRM_SECONDS = 900

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

d = apply_fault(d, vav_reheat_stuck(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### VAV-AHU-LEAVE — VAV leave vs parent AHU SAT (fedBy)
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Air flowing AND |VAV discharge − parent AHU SAT| > band. Needs package topology (vav_to_ahu) so ahu_sat is enriched from the fedBy AHU; otherwise SKIPPED_MISSING_ROLES. Flags broken reheat, bad sensors, or rogue zones.  
**Default confirmation:** 900 s

**Required roles:** `vav-discharge-air-temp`, `ahu-discharge-air-temp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `delta_f` | Leave Δ vs AHU SAT | °F | 8.0 | 2.0–25.0 |
| `flow_on_min` | Airflow-on min | cfm | 25.0 | 0.0–200.0 |

```python
FAULT_CONFIRM_SECONDS = 900

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

d = apply_fault(d, vav_vs_ahu_leave(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### VAV-7 — Min airflow / fixed high flow
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Flow below min SP (when mapped), OR airflow stays flat (low rolling std) at a high mean while air is on (mins too high / box never modulates), OR min_flow_sp itself is excessively high.  
**Default confirmation:** 900 s

**Required roles:** `zone-airflow`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `flow_on_min` | Airflow-on min | cfm | 25.0 | 0.0–200.0 |
| `fixed_flow_max_std` | Fixed-flow max std | cfm | 15.0 | 1.0–80.0 |
| `fixed_flow_min_mean` | Fixed-flow min mean | cfm | 200.0 | 50.0–2000.0 |
| `high_min_flow_sp` | High min-flow SP | cfm | 250.0 | 50.0–2000.0 |

```python
FAULT_CONFIRM_SECONDS = 900

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

d = apply_fault(d, vav7(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

## Central plant / condenser water

### CHW-NOLOAD-1 — Chiller running with no building load
**Family:** `plant` · **Equipment:** `chiller`  
**Equation:** Chiller/plant proven running while building load is satisfied: all mapped zones inside comfort band OR all mapped AHU SAT within sat_band of setpoint. Default confirm 30 min.  
**Default confirmation:** 1800 s

**Optional roles:** `chiller-status`, `chw-pump-status`, `compressor-status`, `building-zone-load-satisfied`, `building-ahu-load-satisfied`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `comfort_low_f` | Comfort low | °F | 70.0 | 60.0–78.0 |
| `comfort_high_f` | Comfort high | °F | 75.0 | 68.0–85.0 |
| `sat_band_f` | AHU SAT≈SP band | °F | 2.0 | 0.5–6.0 |

```python
FAULT_CONFIRM_SECONDS = 1800

def chw_noload1_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Fault: chiller proven running while building load is satisfied.

    Satisfaction: ``building-zone-load-satisfied`` OR ``building-ahu-load-satisfied``
    (injected by load_satisfaction before batch run).
    """
    del poll
    run, kind = mechanical_proof_mask(d, equipment_type="CHILLER")
    d.attrs["chw_noload_proof"] = kind
    if not kind:
        return _false(d.index)

    zone_ok = None
    ahu_ok = None
    if "building-zone-load-satisfied" in d.columns and d["building-zone-load-satisfied"].notna().any():
        zone_ok = as_bool(d["building-zone-load-satisfied"])
    if "building-ahu-load-satisfied" in d.columns and d["building-ahu-load-satisfied"].notna().any():
        ahu_ok = as_bool(d["building-ahu-load-satisfied"])
    if zone_ok is None and ahu_ok is None:
        d.attrs["chw_noload_skip"] = "missing_load_satisfaction"
        return _false(d.index)

    satisfied = _false(d.index)
    if zone_ok is not None:
        satisfied = satisfied | zone_ok.reindex(d.index).fillna(False)
    if ahu_ok is not None:
        satisfied = satisfied | ahu_ok.reindex(d.index).fillna(False)
    return (run & satisfied).fillna(False)

d = apply_fault(d, chw_noload1_compute(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### CHW-1 — Low chilled-water ΔT
**Family:** `plant` · **Equipment:** `chiller`  
**Equation:** Pump on AND (CHWR − CHWS) < 4°F.  
**Default confirmation:** 900 s

**Required roles:** `chilled-water-supply-temp`, `chilled-water-return-temp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `min_dt` | Min ΔT | °F | 4.0 | 1.0–12.0 |

```python
FAULT_CONFIRM_SECONDS = 900

def chw1(d, p, poll):
    min_dt = _f(p, "min_dt", 4.0)
    dt = d["chilled-water-return-temp"] - d["chilled-water-supply-temp"]
    if "chw-pump-cmd" in d.columns:
        pump = norm_cmd(d["chw-pump-cmd"]).fillna(0) > 0.05
    else:
        pump = pd.Series(True, index=d.index)
    return d["chilled-water-supply-temp"].notna() & d["chilled-water-return-temp"].notna() & pump & (dt < min_dt)

d = apply_fault(d, chw1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### CHW-2 — DP below SP at max pump speed
**Family:** `plant` · **Equipment:** `chiller`  
**Equation:** Pump ≥ 87% AND CHW DP < DP SP − 2.2.  
**Default confirmation:** 300 s

**Required roles:** `chw-diff-pressure`, `chw-diff-pressure-sp`, `chw-pump-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `dp_margin` | DP margin | psi | 2.2 | 0.5–6.0 |
| `pump_hi` | Pump high-speed threshold | frac | 0.87 | 0.5–1.0 |

```python
FAULT_CONFIRM_SECONDS = 300

def chw2(d, p, poll):
    margin = _f(p, "dp_margin", 2.2)
    pmp_hi = _f(p, "pump_hi", 0.87)
    pump = norm_cmd(d["chw-pump-cmd"]).fillna(0)
    return (
        d["chw-diff-pressure"].notna() & d["chw-diff-pressure-sp"].notna()
        & (d["chw-diff-pressure"] < d["chw-diff-pressure-sp"] - margin) & (pump >= pmp_hi)
    )

d = apply_fault(d, chw2(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### CHW-3 — Plant supply temp outside deadband
**Family:** `plant` · **Equipment:** `chiller`  
**Equation:** Pump on AND |CHWS − CHWS SP| > 2.2°F.  
**Default confirmation:** 300 s

**Required roles:** `chilled-water-supply-temp`, `chilled-water-supply-temp-sp`, `chw-pump-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `sp_band` | SP band | °F | 2.2 | 0.5–6.0 |

```python
FAULT_CONFIRM_SECONDS = 300

def chw3(d, p, poll):
    band = _f(p, "sp_band", 2.2)
    pump = norm_cmd(d["chw-pump-cmd"]).fillna(0)
    return (
        (pump > 0.01) & d["chilled-water-supply-temp"].notna() & d["chilled-water-supply-temp-sp"].notna()
        & ((d["chilled-water-supply-temp"] < d["chilled-water-supply-temp-sp"] - band) | (d["chilled-water-supply-temp"] > d["chilled-water-supply-temp-sp"] + band))
    )

d = apply_fault(d, chw3(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### CHW-4 — Flow high at max pump
**Family:** `plant` · **Equipment:** `chiller`  
**Equation:** Pump ≥ 87% AND CHW flow > 1100 gpm.  
**Default confirmation:** 300 s

**Required roles:** `chw-flow`, `chw-pump-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `flow_hi` | Flow high | gpm | 1100 | 200–3000 |
| `pump_hi` | Pump high-speed threshold | frac | 0.87 | 0.5–1.0 |

```python
FAULT_CONFIRM_SECONDS = 300

def chw4(d, p, poll):
    flow_hi = _f(p, "flow_hi", 1100.0)
    pmp_hi = _f(p, "pump_hi", 0.87)
    pump = norm_cmd(d["chw-pump-cmd"]).fillna(0)
    return d["chw-flow"].notna() & (d["chw-flow"] > flow_hi) & (pump >= pmp_hi)

d = apply_fault(d, chw4(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### CW-OPT-1 — Condenser water not optimized vs wet-bulb
**Family:** `plant` · **Equipment:** `chiller`, `cooling_tower`  
**Equation:** CW supply significantly colder than web wet-bulb + design approach (Stull WB) — tower over-cooling / not optimized.  
**Default confirmation:** 900 s

**Required roles:** `condenser-water-supply-temp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `cw_approach` | Design approach | °F | 7.0 | 3.0–15.0 |
| `cw_slack` | Slack below target | °F | 2.0 | 0.5–6.0 |

```python
FAULT_CONFIRM_SECONDS = 900

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

d = apply_fault(d, cw_opt(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### CW-APR-1 — High CW approach at full tower fan
**Family:** `plant` · **Equipment:** `chiller`, `cooling_tower`  
**Equation:** At full tower fan speed, leaving CW − web wet-bulb exceeds approach_max (default 8°F, typically 5–10°F). Suspect OA→wet-bulb / CW sensor mismatch or cooling-tower performance degradation.  
**Default confirmation:** 900 s

**Required roles:** `condenser-water-supply-temp`

**Optional roles:** `tower-fan-cmd`, `cw-fan-cmd`, `fan-cmd`, `web-outside-air-wetbulb`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `approach_max_f` | Max approach at full fan | °F | 8.0 | 5.0–15.0 |
| `tower_fan_hi` | Tower fan full-speed threshold | frac | 0.95 | 0.8–1.0 |

```python
FAULT_CONFIRM_SECONDS = 900

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

d = apply_fault(d, cw_apr(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### CW-FAN-1 — Excess tower fan energy vs wet-bulb limit
**Family:** `plant` · **Equipment:** `chiller`, `cooling_tower`  
**Equation:** Tower fans at full speed while leaving CW is well above web wet-bulb + design approach (approach + excess_beyond). Fans are chasing a CW temp that is theoretically hard/impossible — excess fan energy.  
**Default confirmation:** 900 s

**Required roles:** `condenser-water-supply-temp`

**Optional roles:** `tower-fan-cmd`, `cw-fan-cmd`, `fan-cmd`, `web-outside-air-wetbulb`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `cw_approach` | Design approach | °F | 7.0 | 3.0–15.0 |
| `excess_beyond_approach_f` | Excess beyond approach | °F | 5.0 | 2.0–20.0 |
| `tower_fan_hi` | Tower fan full-speed threshold | frac | 0.95 | 0.8–1.0 |

```python
FAULT_CONFIRM_SECONDS = 900

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

d = apply_fault(d, cw_fan_excess(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

## Heat pumps

### HP-1 — Discharge cold when heating
**Family:** `heatpump` · **Equipment:** `heatpump`  
**Equation:** Fan on, zone < 69°F, discharge SAT < 85°F.  
**Default confirmation:** 600 s

**Required roles:** `discharge-air-temp`, `zone-air-temp`, `fan-cmd`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `min_sat` | Min heating SAT | °F | 85.0 | 70.0–110.0 |
| `zone_cold` | Zone cold | °F | 69.0 | 60.0–72.0 |

```python
FAULT_CONFIRM_SECONDS = 600

def hp1(d, p, poll):
    min_sat = _f(p, "min_sat", 85.0)
    zone_cold = _f(p, "zone_cold", 69.0)
    fan = _fan(d)
    return (
        d["discharge-air-temp"].notna() & d["zone-air-temp"].notna() & (fan > FAN_ON_MIN)
        & (d["zone-air-temp"] < zone_cold) & (d["discharge-air-temp"] < min_sat)
    )

d = apply_fault(d, hp1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

## Weather station

### WX-1 — OA temperature spike
**Family:** `weather` · **Equipment:** `weather`  
**Equation:** OAT sample-to-sample jump > 16°F.  
**Default confirmation:** 300 s

**Required roles:** `outside-air-temp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `spike_limit` | Spike limit | °F | 16.0 | 4.0–40.0 |

```python
FAULT_CONFIRM_SECONDS = 300

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

d = apply_fault(d, wx1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

## Trim & respond advisory

### TRIM-1 — Duct static trim advisory
**Family:** `trim` · **Equipment:** `ahu`  
**Equation:** Duct static high (> 1.35 in.w.c.) while VAV pressure requests are low.  
**Default confirmation:** 1800 s

**Required roles:** `duct-static-pressure`, `vav-pressure-request-sum`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `duct_hi` | Duct static high | in. w.c. | 1.35 | 0.5–3.0 |
| `request_lo` | Request sum low | count | 1.0 | 0.0–10.0 |

```python
FAULT_CONFIRM_SECONDS = 1800

def trim1(d, p, poll):
    duct_hi = _f(p, "duct_hi", 1.35)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["duct-static-pressure"].notna() & d["vav-pressure-request-sum"].notna()
        & (d["duct-static-pressure"] > duct_hi) & (d["vav-pressure-request-sum"] < req_lo)
    )

d = apply_fault(d, trim1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### TRIM-3 — HWST trim advisory
**Family:** `trim` · **Equipment:** `boiler`  
**Equation:** HW supply > 160°F while reset requests are low.  
**Default confirmation:** 1800 s

**Required roles:** `hot-water-supply-temp`, `hw-reset-request-sum`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `hwst_hi` | HWST high | °F | 160.0 | 120.0–200.0 |
| `request_lo` | Request sum low | count | 1.0 | 0.0–10.0 |

```python
FAULT_CONFIRM_SECONDS = 1800

def trim3(d, p, poll):
    hwst_hi = _f(p, "hwst_hi", 160.0)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["hot-water-supply-temp"].notna() & d["hw-reset-request-sum"].notna()
        & (d["hot-water-supply-temp"] > hwst_hi) & (d["hw-reset-request-sum"] < req_lo)
    )

d = apply_fault(d, trim3(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### TRIM-4 — CHW plant reset advisory
**Family:** `trim` · **Equipment:** `chiller`  
**Equation:** CHW supply < 45°F while reset requests are low.  
**Default confirmation:** 1800 s

**Required roles:** `chilled-water-supply-temp`, `chw-reset-request-sum`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `chw_lo` | CHWS low | °F | 45.0 | 35.0–55.0 |
| `request_lo` | Request sum low | count | 1.0 | 0.0–10.0 |

```python
FAULT_CONFIRM_SECONDS = 1800

def trim4(d, p, poll):
    chw_lo = _f(p, "chw_lo", 45.0)
    req_lo = _f(p, "request_lo", 1.0)
    return (
        d["chilled-water-supply-temp"].notna() & d["chw-reset-request-sum"].notna()
        & (d["chilled-water-supply-temp"] < chw_lo) & (d["chw-reset-request-sum"] < req_lo)
    )

d = apply_fault(d, trim4(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

## Schedule & occupancy

### SCHED-1 — Unoccupied runtime
**Family:** `schedule` · **Equipment:** `ahu`  
**Equation:** Fan running while occupancy is unoccupied (Overview calendar → occ_mode). When zone_t is mapped, also require zone inside comfort_low_f…comfort_high_f (defaults 70–75°F; synced from Overview zone band).  
**Default confirmation:** 1800 s

**Required roles:** `occupied`, `fan-status`

**Optional roles:** `zone-air-temp`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `comfort_low_f` | Comfort low | °F | 70.0 | 60.0–78.0 |
| `comfort_high_f` | Comfort high | °F | 75.0 | 68.0–85.0 |

```python
FAULT_CONFIRM_SECONDS = 1800

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

d = apply_fault(d, sched1(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

### SCHED-247 — Always-on fan or pump runtime
**Family:** `schedule` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `heatpump`  
**Equation:** Fan or pump (or similar motor proof/command) is on for ≥ always_on_pct of the analysis window — highlights equipment that appears to run 24/7. Applies to all fans and pumps regardless of equipment family when a status/cmd role is mapped.  
**Default confirmation:** 3600 s

**Optional roles:** `fan-status`, `pump-status`, `chw-pump-status`, `hw-pump-status`, `chiller-status`, `compressor-status`, `tower-fan-cmd`, `cw-fan-cmd`, `fan-cmd`, `chw-pump-cmd`, `hw-pump-cmd`, `duct-static-pressure`, `chw-diff-pressure`

**Tunable params**

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `always_on_pct` | Always-on fraction | frac | 0.95 | 0.8–1.0 |
| `pressure_on_min` | Pressure-on evidence | eng | 0.2 | 0.05–2.0 |

```python
FAULT_CONFIRM_SECONDS = 3600

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

d = apply_fault(d, _sched247(d, params, POLL_SECONDS))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS))
```

## Not yet in validated catalog

{: .important }
The following rules remain documented for continuity but are **not** in the current validated vibe19 `RULES` catalog. Do not treat them as Streamlit-parity-tested until they are added to the catalog.

| ID | Title | Family | Notes |
|----|-------|--------|-------|
| `VAV-2` | Night setback miss | `vav` | Zone temp miss setback band during unoccupied hours. |
| `VAV-6` | Reheat when cooling available | `vav` | Reheat valve open while OA is cool enough for free cooling. |
| `TOWER-1` | Cooling tower approach high | `plant` | Tower leaving CW approach above design vs wet-bulb. |
| `CTRL-2` | Generic control loop hunting | `control` | Simplified duct-static hunting screen (pandas-complete logic differs). |
| `RESET-1` | SAT reset not tracking outdoor air | `ahu` | SAT SP not following expected OA reset curve. |
| `OVR-1` | Persistent override | `ahu` | Manual override / hand mode held beyond confirm window. |
| `OA-2` | DCV minimum OA not met | `ahu` | Estimated OA fraction below DCV/minimum OA setpoint. |
| `PLANT-1` | CHW DP reset missing | `plant` | CHW differential pressure SP not resetting with load. |
| `SP-HIGH` | Occupied setpoint too high | `vav` | Occupied zone SP above comfort policy. |
| `SP-LOW` | Occupied setpoint too low | `vav` | Occupied zone SP below comfort policy. |
| `KPI-1` | Performance score (advisory) | `site` | Site-level advisory KPI aggregation. |
| `TRIM-2` | Chiller plant enable advisory | `trim` | Trim/respond chiller enable advisory. |
| `WX-2` | Gust lower than sustained wind | `weather` | Wind gust reading inconsistent with sustained wind. |

---

## Framework docs

- [Rule Cookbook hub](index.html)
- [DataFusion SQL cookbook](datafusion-sql-cookbook.html)
- [P0 rule catalog](p0-rule-catalog.html)
- [Parity matrix](parity-matrix.html)
- [Prerequisite macros](prerequisite-macros.html)
- [Benchmark strategy](benchmark-strategy.html)
