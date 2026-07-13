---
title: Pandas cookbook
parent: Rule Cookbook
nav_order: 2
---

# Pandas FDD Cookbook

**For analyst workflows outside Open-FDD.** Open-FDD edge runs **Rust + Apache Arrow + DataFusion SQL** only. This cookbook mirrors every rule in the [DataFusion SQL cookbook](datafusion-sql-cookbook.html) for notebooks, CSV exports, RCx studies, and parity testing.

---

## Table of contents

1. [Setup & shared helpers](#setup--shared-helpers)
2. [Fault confirmation delay (default 5 minutes)](#fault-confirmation-delay-default-5-minutes)
3. [Sensor validation](#sensor-validation)
4. [Air handling units (FC1–FC15)](#air-handling-units)
5. [VAV zones](#vav-zones)
6. [Economizer & ventilation](#economizer--ventilation)
   - [AHU economizer diagnostics guide](#ahu-economizer-diagnostics-guide)
   - [ECON-1–5](#econ-1--economizer-stuck-closed)
   - [Ventilation & leakage cross-rules](#rule-map-economizer-family)
7. [Central plants](#central-plants)
8. [Heat pumps](#heat-pumps)
9. [Weather station](#weather-station)
10. [Trim & respond advisory](#trim--respond-advisory)
11. [Extended rule families (v2)](#extended-rule-families-v2)
12. [Extended rule families (P2)](#extended-rule-families-p2)
13. [Framework docs](#framework-docs)
14. [Export to Open-FDD SQL](#export-to-open-fdd-sql)

---

## Setup & shared helpers

```python
import pandas as pd
import numpy as np

# Generic CSV (vendor export, BMS dump, Open-FDD batch export, etc.)
df = pd.read_csv("your_building_data.csv")

# Optional: parse timestamp column (rename "timestamp" if your file uses another name)
ts_col = "timestamp"  # e.g. "DateTime", "time", "ts"
if ts_col in df.columns:
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=[ts_col]).sort_values(ts_col)
else:
    df = df.sort_index()

# Optional: filter one equipment / site column if present
# EQUIP = "equip:your-ahu"
# d = df[df["equipment_id"] == EQUIP].copy() if "equipment_id" in df.columns else df.copy()
d = df.copy()
```

### Normalize command 0–100 → 0–1

```python
def norm_cmd(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    return np.where(s > 1.0, s / 100.0, s)
```

### Apply fault mask helper

```python
def apply_fault(d: pd.DataFrame, mask: pd.Series, col: str = "fault_raw") -> pd.DataFrame:
    d = d.copy()
    d[col] = mask.fillna(False)
    return d
```

### Prerequisite macros (shared with SQL cookbook)

```python
def macro_fan_proven_on(d: pd.DataFrame) -> pd.Series:
    cmd = norm_cmd(d["fan_cmd"]) if "fan_cmd" in d else pd.Series(0.0, index=d.index)
    on = cmd >= 0.05
    if "fan_status" in d.columns:
        st = d["fan_status"]
        return on & (st.isna() | st.astype(bool))
    return on

def macro_override_suppression(d: pd.DataFrame) -> pd.Series:
    mask = pd.Series(True, index=d.index)
    for col in ("override_active", "hand_mode", "bypass_active"):
        if col in d.columns:
            mask &= ~d[col].fillna(False).astype(bool)
    return mask
```

See [prerequisite macros](prerequisite-macros.html) for full library.

---

## Fault confirmation delay (default 5 minutes)

Every rule below uses an adjustable delay before a fault is considered **confirmed**. Default matches Open-FDD edge: **5 minutes**.

```python
# --- ADJUSTABLE: default 5 min fault delay ---
POLL_SECONDS = 60                    # historian poll interval
FAULT_CONFIRM_SECONDS = 300          # default 5 minutes — change per rule
FAULT_CONFIRM_ROWS = max(1, FAULT_CONFIRM_SECONDS // POLL_SECONDS)

def confirm_fault(raw: pd.Series, min_rows: int = FAULT_CONFIRM_ROWS) -> pd.Series:
    """True only after `min_rows` consecutive True samples."""
    groups = (raw != raw.shift()).cumsum()
    streak = raw.groupby(groups).cumcount() + 1
    return raw & (streak >= min_rows)

# Example: FC4 PID hunting often needs longer delay
FC4_CONFIRM_SECONDS = 3600
FC4_CONFIRM_ROWS = FC4_CONFIRM_SECONDS // POLL_SECONDS
```

At 60 s poll, `FAULT_CONFIRM_ROWS=5` ≈ 300 s — same as SQL `confirmation_seconds: 300`.

---

## Sensor validation

### SV-1 — Zone temperature out of range

```python
FAULT_CONFIRM_SECONDS = 300  # adjustable

mask = d["zone_t"].notna() & ((d["zone_t"] < 55.0) | (d["zone_t"] > 90.0))
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### SV-2 — OA temperature out of range

```python
FAULT_CONFIRM_SECONDS = 300

mask = d["oa_t"].notna() & ((d["oa_t"] < 40.0) | (d["oa_t"] > 110.0))
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### SV-3 — OA humidity out of range

```python
FAULT_CONFIRM_SECONDS = 300

mask = d["oa_h"].notna() & ((d["oa_h"] < 10.0) | (d["oa_h"] > 95.0))
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### SV-4 — Mixing envelope (MAT vs OAT/RAT)

Prefer envelope checks when OAT, RAT, and MAT are present — mirrors [FC2/FC3](datafusion-sql-cookbook.html#air-handling-units) logic.

```python
FAULT_CONFIRM_SECONDS = 300
ENV = 2.2

mask = (
    d["mat"].notna() & d["oa_t"].notna() & d["rat"].notna()
    & (
        (d["mat"] < d[["oa_t", "rat"]].min(axis=1) - ENV)
        | (d["mat"] > d[["oa_t", "rat"]].max(axis=1) + ENV)
    )
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### SV-5 — Stale data (no recent samples)

```python
FAULT_CONFIRM_SECONDS = 300
STALE_MINUTES = 30

last_ts = d.groupby("equipment_id")["timestamp"].transform("max")
stale = (d["timestamp"] == last_ts) & (
    (pd.Timestamp.utcnow() - last_ts).dt.total_seconds() > STALE_MINUTES * 60
)
d = apply_fault(d, stale)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### SV-6 — Flatline (stuck sensor)

```python
FAULT_CONFIRM_SECONDS = 300
FLATLINE_SAMPLES = 12  # ~1 h @ 5-min poll

def flatline_mask(series: pd.Series, tol: float = 0.10, window: int = FLATLINE_SAMPLES) -> pd.Series:
    roll_min = series.rolling(window, min_periods=window).min()
    roll_max = series.rolling(window, min_periods=window).max()
    return series.notna() & ((roll_max - roll_min) <= tol)

d = apply_fault(d, flatline_mask(d["oa_t"], tol=0.10))
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### SV-7 — Rate-of-change spike (maps to `SV-SPIKE`)

Abrupt **per-sample** discontinuity — not the sustained slew rule. Production IDs:

* `SV-SPIKE` — sample jump (this section)  
* `SV-SLEW` — time-normalized rate with OFF / STARTUP_TRANSIENT / RUNNING_STEADY thresholds — see [sensor rate profiles](sensor-rate-profiles.html)

```python
FAULT_CONFIRM_SECONDS = 300
SPIKE_LIMIT = 16.0  # °F per sample (OA example; prefer profile limits)

mask = d["oa_t"].notna() & (d["oa_t"].diff().abs() > SPIKE_LIMIT)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

Sustained slew (illustrative — prefer profile registry):

```python
dt_h = d["timestamp"].diff().dt.total_seconds() / 3600.0
rate = d["zone_t"].diff().abs() / dt_h
# use steady vs transient fault from sensor_rate_profiles.yaml
```

---

## Air handling units

Shared tunables (match SQL cookbook):

```python
MIX_TOL = 1.15
SUPPLY_TOL = 1.15
AHU_MIN_OA_DPR = 0.05
DELTA_SUPPLY_FAN = 0.55
FAN_ON_MIN = 0.01
```

---

### FC1 — Duct static below SP at full fan (GL36 Rule A)

```python
FAULT_CONFIRM_SECONDS = 300
DUCT_STATIC_ERR = 0.12
FAN_HI = 0.87

fan = norm_cmd(d["fan_cmd"])
mask = (
    d["duct_static"].notna() & d["duct_static_sp"].notna()
    & (d["duct_static"] < d["duct_static_sp"] - DUCT_STATIC_ERR)
    & (fan >= FAN_HI)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC2 — MAT below OAT/RAT envelope (GL36 Rule B)

```python
FAULT_CONFIRM_SECONDS = 600

fan = norm_cmd(d["fan_cmd"])
mask = (
    fan > FAN_ON_MIN
    & d["mat"].notna() & d["oat"].notna() & d["rat"].notna()
    & ((d["mat"] - MIX_TOL) < np.minimum(d["rat"] - MIX_TOL, d["oat"] - MIX_TOL))
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC3 — MAT above OAT/RAT envelope (GL36 Rule C)

```python
FAULT_CONFIRM_SECONDS = 600

fan = norm_cmd(d["fan_cmd"])
mask = (
    fan > FAN_ON_MIN
    & d["mat"].notna() & d["oat"].notna() & d["rat"].notna()
    & ((d["mat"] - MIX_TOL) > np.maximum(d["rat"] + MIX_TOL, d["oat"] + MIX_TOL))
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC4 — PID hunting (operating-state oscillation)

Reference implementation matching Open-FDD AHU `FaultConditionFour`. Counts operating-mode **entry transitions per hour**; flags when any hour exceeds `DELTA_OS_MAX`.

```python
FAULT_CONFIRM_SECONDS = 3600  # PID hunting: use 1 h+ confirmation
DELTA_OS_MAX = 5
AHU_MIN_OA_DPR = 0.05

htg = norm_cmd(d["htg_valve_pct"])
clg = norm_cmd(d["clg_valve_pct"])
fan = norm_cmd(d["fan_cmd"])
econ = norm_cmd(d["oa_damper_pct"])

d["heating_mode"] = (
    (htg > 0) & (clg == 0) & (fan > 0) & (econ == AHU_MIN_OA_DPR)
).astype(int)
d["econ_only_cooling_mode"] = (
    (htg == 0) & (clg == 0) & (fan > 0) & (econ > AHU_MIN_OA_DPR)
).astype(int)
d["econ_plus_mech_cooling_mode"] = (
    (htg == 0) & (clg > 0) & (fan > 0) & (econ > AHU_MIN_OA_DPR)
).astype(int)
d["mech_cooling_only_mode"] = (
    (htg == 0) & (clg > 0) & (fan > 0) & (econ == AHU_MIN_OA_DPR)
).astype(int)

mode_cols = [
    "heating_mode", "econ_only_cooling_mode",
    "econ_plus_mech_cooling_mode", "mech_cooling_only_mode",
]
hourly = d.set_index("timestamp")[mode_cols].resample("H").apply(
    lambda x: (x.eq(1) & x.shift().ne(1)).sum()
)
raw_hourly = hourly[hourly.columns].gt(DELTA_OS_MAX).any(axis=1).astype(int)
# Broadcast hourly flag back to sample index (forward-fill within hour)
d["fault_raw"] = False
for ts, flag in raw_hourly.items():
    if flag:
        d.loc[d["timestamp"].dt.floor("H") == ts.floor("H"), "fault_raw"] = True

d["fault_confirmed"] = confirm_fault(
    d["fault_raw"], min_rows=FC4_CONFIRM_ROWS
)
```

---

### FC5 — SAT cold when heating commanded (GL36 Rule D)

```python
FAULT_CONFIRM_SECONDS = 600

fan = norm_cmd(d["fan_cmd"])
htg = norm_cmd(d["htg_valve_pct"])
mask = (
    d["sat"].notna() & d["mat"].notna()
    & (fan > FAN_ON_MIN) & (htg > 0.01)
    & ((d["sat"] + SUPPLY_TOL) <= (d["mat"] - MIX_TOL + DELTA_SUPPLY_FAN))
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC6 — Estimated OA fraction mismatch

```python
FAULT_CONFIRM_SECONDS = 600
AIRFLOW_ERR = 0.15
OAT_RAT_DELTA_MIN = 5.0
AHU_MIN_CFM_DESIGN = 5000.0  # tune per site

fan = norm_cmd(d["fan_cmd"])
htg = norm_cmd(d["htg_valve_pct"])
clg = norm_cmd(d["clg_valve_pct"])
econ = norm_cmd(d["oa_damper_pct"])

d["rat_minus_oat"] = (d["rat"] - d["oat"]).abs()
d["percent_oa_calc"] = ((d["mat"] - d["rat"]) / (d["oat"] - d["rat"]).replace(0, np.nan)).clip(lower=0)
d["perc_OAmin"] = AHU_MIN_CFM_DESIGN / d["vav_total_flow"].replace(0, np.nan)
d["oa_err"] = (d["percent_oa_calc"] - d["perc_OAmin"]).abs()

os1 = (htg > 0) & (fan > 0)
os4 = (htg == 0) & (clg > 0) & (fan > 0) & (econ == AHU_MIN_OA_DPR)

mask = (
    d["mat"].notna() & d["oat"].notna() & d["rat"].notna() & d["vav_total_flow"].notna()
    & (d["rat_minus_oat"] >= OAT_RAT_DELTA_MIN)
    & (d["oa_err"] > AIRFLOW_ERR)
    & (os1 | os4)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC7 — SAT low with full heating (GL36 Rule E)

```python
FAULT_CONFIRM_SECONDS = 600
SAT_ERR = 1.0

fan = norm_cmd(d["fan_cmd"])
htg = norm_cmd(d["htg_valve_pct"])
mask = (
    d["sat"].notna() & d["sat_sp"].notna()
    & (fan > FAN_ON_MIN)
    & (d["sat"] < d["sat_sp"] - SAT_ERR)
    & (htg > 0.9)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC8 — SAT above blend in economizer mode (GL36 Rule F)

```python
FAULT_CONFIRM_SECONDS = 600

econ = norm_cmd(d["oa_damper_pct"])
clg = norm_cmd(d["clg_valve_pct"])
d["sat_mat_err"] = (d["sat"] - DELTA_SUPPLY_FAN - d["mat"]).abs()
d["sqrt_tol"] = np.sqrt(SUPPLY_TOL**2 + MIX_TOL**2)

mask = (
    d["sat"].notna() & d["mat"].notna()
    & (econ > AHU_MIN_OA_DPR) & (clg < 0.1)
    & (d["sat_mat_err"] > d["sqrt_tol"])
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC9 — OAT too warm for free cooling (GL36 Rule G)

```python
FAULT_CONFIRM_SECONDS = 600

econ = norm_cmd(d["oa_damper_pct"])
clg = norm_cmd(d["clg_valve_pct"])

mask = (
    d["oat"].notna() & d["sat_sp"].notna()
    & (econ > AHU_MIN_OA_DPR) & (clg < 0.1)
    & ((d["oat"] - MIX_TOL) > (d["sat_sp"] - DELTA_SUPPLY_FAN + MIX_TOL))
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC10 — OAT/MAT mismatch + mech cooling (GL36 Rule H)

```python
FAULT_CONFIRM_SECONDS = 600

econ = norm_cmd(d["oa_damper_pct"])
clg = norm_cmd(d["clg_valve_pct"])
d["abs_mat_oat"] = (d["mat"] - d["oat"]).abs()
d["sqrt_tol"] = np.sqrt(MIX_TOL**2 + MIX_TOL**2)

mask = (
    d["mat"].notna() & d["oat"].notna()
    & (clg > 0.01) & (econ > 0.9)
    & (d["abs_mat_oat"] > d["sqrt_tol"])
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC11 — OAT/MAT mismatch economizer-only (GL36 Rule I)

```python
FAULT_CONFIRM_SECONDS = 600

econ = norm_cmd(d["oa_damper_pct"])
clg = norm_cmd(d["clg_valve_pct"])

mask = (
    d["oat"].notna() & d["sat_sp"].notna()
    & (clg > 0.01) & (econ > 0.9)
    & ((d["oat"] + MIX_TOL) < (d["sat_sp"] - DELTA_SUPPLY_FAN - MIX_TOL))
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC12 — SAT above blend in cooling (GL36 Rule J)

```python
FAULT_CONFIRM_SECONDS = 600

econ = norm_cmd(d["oa_damper_pct"])
clg = norm_cmd(d["clg_valve_pct"])
sat_check = d["sat"] - SUPPLY_TOL - DELTA_SUPPLY_FAN
mat_check = d["mat"] + MIX_TOL

mask = (
    d["sat"].notna() & d["mat"].notna() & (clg > 0.01)
    & (sat_check > mat_check)
    & ((econ == AHU_MIN_OA_DPR) | (econ > 0.9))
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC13 — SAT above SP at full cooling (GL36 Rule K)

```python
FAULT_CONFIRM_SECONDS = 600
SAT_ERR = 1.0

econ = norm_cmd(d["oa_damper_pct"])
clg = norm_cmd(d["clg_valve_pct"])

mask = (
    d["sat"].notna() & d["sat_sp"].notna() & (clg > 0.01)
    & (d["sat"] > d["sat_sp"] + SAT_ERR)
    & ((econ == AHU_MIN_OA_DPR) | (econ > 0.9))
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC14 — CHW coil ΔT when inactive (GL36 Rule L)

```python
FAULT_CONFIRM_SECONDS = 600
COIL_TOL = 1.15

econ = norm_cmd(d["oa_damper_pct"])
clg = norm_cmd(d["clg_valve_pct"])
htg = norm_cmd(d["htg_valve_pct"])
fan = norm_cmd(d["fan_cmd"])

d["clg_delta"] = d["clg_coil_enter_t"] - d["clg_coil_leave_t"]
d["clg_sqrt"] = np.sqrt(COIL_TOL**2 + COIL_TOL**2) + DELTA_SUPPLY_FAN

mask = (
    d["clg_coil_enter_t"].notna() & d["clg_coil_leave_t"].notna()
    & (d["clg_delta"] >= d["clg_sqrt"])
    & (((econ > AHU_MIN_OA_DPR) & (clg < 0.1)) | ((htg > 0) & (fan > 0)))
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### FC15 — HW coil ΔT when inactive (GL36 Rule M)

```python
FAULT_CONFIRM_SECONDS = 600
COIL_TOL = 1.15

econ = norm_cmd(d["oa_damper_pct"])
clg = norm_cmd(d["clg_valve_pct"])

d["htg_delta"] = d["htg_coil_enter_t"] - d["htg_coil_leave_t"]
d["htg_sqrt"] = np.sqrt(COIL_TOL**2 + COIL_TOL**2) + DELTA_SUPPLY_FAN

mask = (
    d["htg_coil_enter_t"].notna() & d["htg_coil_leave_t"].notna()
    & (d["htg_delta"] >= d["htg_sqrt"])
    & (
        ((econ > AHU_MIN_OA_DPR) & (clg < 0.1))
        | ((clg > 0.01) & (econ == AHU_MIN_OA_DPR))
        | ((clg > 0.01) & (econ > 0.9))
    )
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

### AHU — Additional patterns

#### SAT deviation from setpoint

```python
FAULT_CONFIRM_SECONDS = 600
ERR = 5.0

mask = d["sat"].notna() & d["sat_sp"].notna() & (d["sat"].sub(d["sat_sp"]).abs() > ERR)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

#### Duct static pressure high

```python
FAULT_CONFIRM_SECONDS = 300
MARGIN = 0.25

mask = d["duct_static"].notna() & d["duct_static_sp"].notna() & (
    d["duct_static"] > d["duct_static_sp"] + MARGIN
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

#### Fan off but duct still warm

```python
FAULT_CONFIRM_SECONDS = 600
DELTA = 15.0

mask = (
    d["fan_cmd"].notna() & d["duct_t"].notna() & d["oa_t"].notna()
    & (d["fan_cmd"] == False) & (d["duct_t"] > d["oa_t"] + DELTA)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

#### Heating and cooling simultaneous

```python
FAULT_CONFIRM_SECONDS = 300

mask = d["htg_valve_pct"].notna() & d["clg_valve_pct"].notna() & (
    (d["htg_valve_pct"] > 10.0) & (d["clg_valve_pct"] > 10.0)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

## VAV zones

### VAV-1 — Zone comfort band

```python
FAULT_CONFIRM_SECONDS = 900

v = df[df["equipment_id"] == "equip:your-vav"].copy()
mask = v["zone_t"].notna() & ((v["zone_t"] < 68.0) | (v["zone_t"] > 76.0))
v = apply_fault(v, mask)
v["fault_confirmed"] = confirm_fault(v["fault_raw"])
```

### VAV-2 — Night setback miss

```python
FAULT_CONFIRM_SECONDS = 1800

mask = v["zone_t"].notna() & v["occ_mode"].notna() & (
    (v["occ_mode"] == "unoccupied") & (v["zone_t"] > 78.0)
)
v = apply_fault(v, mask)
v["fault_confirmed"] = confirm_fault(v["fault_raw"])
```

### VAV-3 — Excessive reheat during warm weather

```python
FAULT_CONFIRM_SECONDS = 300

reheat = norm_cmd(v["reheat_valve_pct"])
mask = v["oa_t"].notna() & (v["oa_t"] > 78.0) & (reheat > 0.52)
v = apply_fault(v, mask)
v["fault_confirmed"] = confirm_fault(v["fault_raw"])
```

### VAV-4 — Damper stuck at full open

```python
FAULT_CONFIRM_SECONDS = 900
FULL_OPEN = 97.5
ROLL = 105  # samples sustained

mask = (
    v["damper_pct"].notna()
    & (v["damper_pct"] > FULL_OPEN)
    & (v["damper_pct"].rolling(ROLL, min_periods=ROLL).min() > FULL_OPEN)
)
v = apply_fault(v, mask)
v["fault_confirmed"] = confirm_fault(v["fault_raw"])
```

---

## Economizer & ventilation

Analyst mirror of the [DataFusion economizer section](datafusion-sql-cookbook.html#economizer--ventilation). Use the same semantic columns and thresholds; export CSV from Open-FDD or vendor BMS for off-box RCx.

### AHU economizer diagnostics guide

#### Operating modes (GL36-style)

```python
AHU_MIN_OA_DPR = 0.05  # minimum OA damper position (0–1), tune per site

def operating_mode_row(row) -> str:
    """Classify one sample into OS1–OS4 (simplified GL36 bands)."""
    htg = norm_cmd(pd.Series([row.get("htg_valve_pct", 0)])).iloc[0]
    clg = norm_cmd(pd.Series([row.get("clg_valve_pct", 0)])).iloc[0]
    fan = norm_cmd(pd.Series([row.get("fan_cmd", 0)])).iloc[0]
    econ = norm_cmd(pd.Series([row.get("oa_damper_pct", 0)])).iloc[0]
    if fan < 0.05:
        return "off"
    if htg > 0 and clg == 0:
        return "OS1_heating"
    if htg == 0 and clg == 0 and econ > AHU_MIN_OA_DPR:
        return "OS2_economizer"
    if htg == 0 and clg > 0 and econ > AHU_MIN_OA_DPR:
        return "OS3_econ_mech"
    if htg == 0 and clg > 0 and econ <= AHU_MIN_OA_DPR + 0.02:
        return "OS4_mech_only"
    return "other"
```

| Mode | Typical fault rules |
|------|---------------------|
| OS1 | FC5, FC7, ECON-5 |
| OS2 | ECON-1, ECON-2 |
| OS3 | ECON-3, FC8–FC11 |
| OS4 | ECON-3 (inverse), cooling valve faults |

#### Required columns

Same semantic IDs as SQL: `oa_t`, `mat`, `rat`/`ra_t`, `oa_damper_pct`, `clg_valve_pct`, `htg_valve_pct`, `fan_cmd`, `fan_status`, `sat`, `sat_sp`, optional `oa_h`/`ra_h` for enthalpy sites.

#### Core formulas

```python
def estimate_oa_fraction(d: pd.DataFrame) -> pd.Series:
    """Dry-bulb OA fraction; NaN when mixing signal too weak."""
    denom = (d["oa_t"] - d["rat"]).replace(0, np.nan)
    frac = (d["mat"] - d["rat"]) / denom
    weak = (d["rat"] - d["oa_t"]).abs() < 2.2
    return frac.where(~weak)

d["oa_frac"] = estimate_oa_fraction(d)
```

**Dry-bulb favorable:** `fan_proven & (oa_t < 63.0)` — align `63` with site `oat_cutoff`.

**Enthalpy (optional):** compute outdoor/return enthalpy in the notebook (psychrometric library); gate economizer rules on `h_oa < h_ra` instead of OAT-only when the controller uses enthalpy logic.

#### RCx diagnostic workflow

1. Filter one AHU: `d = df[df["equipment_id"] == "equip:your-ahu"].copy()`
2. Run sensor validation masks (SV section) on `oa_t`, `mat`, `rat`.
3. Plot `oa_t`, `mat`, `rat`, `oa_damper_pct` for a summer weekday.
4. Apply ECON-1 → ECON-5 below; cross-check OA-1, DMP-1 in [Extended v2](#oa-1--low-oa-fraction).
5. Export confirmed intervals to Open-FDD SQL via [Export to Open-FDD SQL](#export-to-open-fdd-sql).

#### Rule map (economizer family)

| Rule | Focus | Section |
|------|-------|---------|
| ECON-1–5 | Core economizer faults | below |
| OA-1, OA-2 | Ventilation minimum / DCV | [Extended v2 / P2](#oa-1--low-oa-fraction) |
| DMP-1 | OA damper leakage | [Extended v2](#dmp-1--oa-damper-leakage) |
| FC6, FC8–FC11 | GL36 economizer-mode AHU faults | [Air handling units](#air-handling-units) |

---

### ECON-1 — Economizer stuck closed

```python
FAULT_CONFIRM_SECONDS = 600

mask = (
    d["fan_cmd"].astype(bool)
    & d["oa_damper_pct"].notna() & d["oa_t"].notna()
    & (d["oa_damper_pct"] < 5.0) & (d["oa_t"] > 55.0)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### ECON-2 — Economizing when outdoor unfavorable

```python
FAULT_CONFIRM_SECONDS = 300

mask = d["oa_t"].notna() & d["oa_damper_pct"].notna() & (
    (d["oa_t"] > 63.0) & (d["oa_damper_pct"] > 0.42)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### ECON-3 — Mech cooling when econ available

```python
FAULT_CONFIRM_SECONDS = 300

mask = (
    d["oa_t"].notna() & d["oa_damper_pct"].notna() & d["clg_valve_pct"].notna()
    & (d["oa_t"] < 63.0) & (d["oa_damper_pct"] < 0.32) & (d["clg_valve_pct"] > 0.01)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### ECON-4 — Low estimated OA fraction

```python
FAULT_CONFIRM_SECONDS = 600
OA_MIN_PCT = 21.0

fan = norm_cmd(d["fan_cmd"])
d["oa_frac"] = (d["mat"] - d["rat"]) / (d["oat"] - d["rat"]).replace(0, np.nan) * 100.0

mask = (
    fan > FAN_ON_MIN
    & d["mat"].notna() & d["rat"].notna() & d["oat"].notna()
    & ((d["rat"] - d["oat"]).abs() > 2.2)
    & (d["oa_frac"] < OA_MIN_PCT)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### ECON-5 — Preheat over-conditioning

```python
FAULT_CONFIRM_SECONDS = 600

mask = (
    d["preheat_leave_t"].notna() & d["sat_sp"].notna() & d["oa_t"].notna() & d["htg_valve_pct"].notna()
    & (d["htg_valve_pct"] > 0.01)
    & (
        ((d["oa_t"] > d["sat_sp"]) & (d["preheat_leave_t"] - d["oa_t"] > 2.2))
        | ((d["oa_t"] < d["sat_sp"]) & (d["preheat_leave_t"] - d["sat_sp"] > 2.2))
    )
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

## Central plants

### CHW-1 — Low chilled-water delta-T

```python
FAULT_CONFIRM_SECONDS = 900
MIN_DT = 4.0

p = df[df["equipment_id"] == "equip:your-chiller-plant"].copy()
p["chw_dt"] = p["chw_return_t"] - p["chw_supply_t"]
mask = (
    p["chw_supply_t"].notna() & p["chw_return_t"].notna()
    & p["chw_pump_cmd"].astype(bool)
    & (p["chw_dt"] < MIN_DT)
)
p = apply_fault(p, mask)
p["fault_confirmed"] = confirm_fault(p["fault_raw"])
```

### CHW-2 — DP below SP at max pump speed

```python
FAULT_CONFIRM_SECONDS = 300
DP_MARGIN = 2.2
PMP_HI = 0.87

pump = norm_cmd(p["chw_pump_cmd"])
mask = (
    p["chw_dp"].notna() & p["chw_dp_sp"].notna()
    & (p["chw_dp"] < p["chw_dp_sp"] - DP_MARGIN)
    & (pump >= PMP_HI)
)
p = apply_fault(p, mask)
p["fault_confirmed"] = confirm_fault(p["fault_raw"])
```

### CHW-3 — Plant supply temp outside deadband

```python
FAULT_CONFIRM_SECONDS = 300
SP_BAND = 2.2

pump = norm_cmd(p["chw_pump_cmd"])
mask = (
    pump > 0.01
    & p["chw_supply_t"].notna() & p["chw_supply_t_sp"].notna()
    & (
        (p["chw_supply_t"] < p["chw_supply_t_sp"] - SP_BAND)
        | (p["chw_supply_t"] > p["chw_supply_t_sp"] + SP_BAND)
    )
)
p = apply_fault(p, mask)
p["fault_confirmed"] = confirm_fault(p["fault_raw"])
```

### CHW-4 — Flow high at max pump

```python
FAULT_CONFIRM_SECONDS = 300
FLOW_HI = 1100.0
PMP_HI = 0.87

pump = norm_cmd(p["chw_pump_cmd"])
mask = p["chw_flow"].notna() & (p["chw_flow"] > FLOW_HI) & (pump >= PMP_HI)
p = apply_fault(p, mask)
p["fault_confirmed"] = confirm_fault(p["fault_raw"])
```

---

## Heat pumps

### HP-1 — Discharge cold when heating

```python
FAULT_CONFIRM_SECONDS = 600
MIN_SAT = 85.0
ZONE_COLD = 69.0

hp = df[df["equipment_id"] == "equip:your-hp"].copy()
fan = norm_cmd(hp["fan_cmd"])
mask = (
    hp["sat"].notna() & hp["zone_t"].notna()
    & (fan > FAN_ON_MIN)
    & (hp["zone_t"] < ZONE_COLD)
    & (hp["sat"] < MIN_SAT)
)
hp = apply_fault(hp, mask)
hp["fault_confirmed"] = confirm_fault(hp["fault_raw"])
```

---

## Weather station

### WX-1 — Temperature spike

```python
FAULT_CONFIRM_SECONDS = 300
SPIKE_LIMIT = 16.0

wx = df[df["equipment_id"] == "equip:weather-station"].copy()
mask = wx["oa_t"].notna() & (wx["oa_t"].diff().abs() > SPIKE_LIMIT)
wx = apply_fault(wx, mask)
wx["fault_confirmed"] = confirm_fault(wx["fault_raw"])
```

### WX-2 — Gust lower than sustained wind

```python
FAULT_CONFIRM_SECONDS = 300

mask = wx["wind_gust"].notna() & wx["wind_speed"].notna() & (wx["wind_gust"] < wx["wind_speed"])
wx = apply_fault(wx, mask)
wx["fault_confirmed"] = confirm_fault(wx["fault_raw"])
```

---

## Trim & respond advisory

Use **`FAULT_CONFIRM_SECONDS = 1800`** or higher for advisory rules.

### TRIM-1 — Duct static trim advisory

```python
FAULT_CONFIRM_SECONDS = 1800

mask = (
    d["duct_static"].notna() & d["vav_press_req_sum"].notna()
    & (d["duct_static"] > 0.80) & (d["vav_press_req_sum"] < 1.0)
    & (d["duct_static"] > 1.35)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=FAULT_CONFIRM_SECONDS // POLL_SECONDS)
```

### TRIM-2 — Chiller plant enable advisory

```python
FAULT_CONFIRM_SECONDS = 1800

p = df[df["equipment_id"] == "equip:your-chiller-plant"].copy()
mask = p["chw_valve_req_count"].notna() & (p["chw_valve_req_count"] < 2)
p = apply_fault(p, mask)
p["fault_confirmed"] = confirm_fault(p["fault_raw"], min_rows=FAULT_CONFIRM_SECONDS // POLL_SECONDS)
```

### TRIM-3 — HWST trim advisory

```python
FAULT_CONFIRM_SECONDS = 1800

hw = df[df["equipment_id"] == "equip:your-hw-plant"].copy()
mask = hw["hw_supply_t"].notna() & hw["hw_reset_req_sum"].notna() & (
    (hw["hw_supply_t"] > 160.0) & (hw["hw_reset_req_sum"] < 1.0)
)
hw = apply_fault(hw, mask)
hw["fault_confirmed"] = confirm_fault(hw["fault_raw"], min_rows=FAULT_CONFIRM_SECONDS // POLL_SECONDS)
```

### TRIM-4 — CHW plant reset advisory

```python
FAULT_CONFIRM_SECONDS = 1800

mask = p["chw_supply_t"].notna() & p["chw_reset_req_sum"].notna() & (
    (p["chw_supply_t"] < 45.0) & (p["chw_reset_req_sum"] < 1.0)
)
p = apply_fault(p, mask)
p["fault_confirmed"] = confirm_fault(p["fault_raw"], min_rows=FAULT_CONFIRM_SECONDS // POLL_SECONDS)
```

---

## Extended rule families (v2)

Mirrors [DataFusion SQL v2 section](datafusion-sql-cookbook.html#extended-rule-families-v2). Import [prerequisite macros](prerequisite-macros.html) helpers as needed.

### RESET-1 — SAT reset not tracking outdoor air

```python
FAULT_CONFIRM_SECONDS = 900
SAT_RESET_ERR = 3.0

def expected_sat_sp(oat: pd.Series) -> pd.Series:
    return 52.0 + 0.25 * (oat - 65.0)

base = macro_fan_proven_on(d) if "fan_cmd" in d else pd.Series(True, index=d.index)
mask = (
    base & d["sat_sp"].notna() & d["oat"].notna()
    & (d["sat_sp"].sub(expected_sat_sp(d["oat"])).abs() > SAT_RESET_ERR)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=FAULT_CONFIRM_SECONDS // POLL_SECONDS)
```

### SCHED-1 — Unoccupied runtime

```python
FAULT_CONFIRM_SECONDS = 1800
mask = d["occ_mode"].eq("unoccupied") & d["fan_status"].astype(bool)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=FAULT_CONFIRM_SECONDS // POLL_SECONDS)
```

### OVR-1 — Persistent override

```python
FAULT_CONFIRM_SECONDS = 3600
mask = d["override_active"].fillna(False).astype(bool)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=FAULT_CONFIRM_SECONDS // POLL_SECONDS)
```

### CMD-1 — Fan cmd/status mismatch

```python
FAULT_CONFIRM_SECONDS = 600
cmd_on = norm_cmd(d["fan_cmd"]) >= 0.05
mask = d["fan_status"].notna() & (cmd_on != d["fan_status"].astype(bool))
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### OA-1 — Low OA fraction

```python
FAULT_CONFIRM_SECONDS = 900
MIN_OA = 0.15
oa_frac = (d["mat"] - d["rat"]) / (d["oa_t"] - d["rat"]).replace(0, np.nan)
mask = (
    d["fan_status"].astype(bool) & d["oa_t"].notna() & d["rat"].notna() & d["mat"].notna()
    & ((d["rat"] - d["oa_t"]).abs() > 0.5) & (oa_frac < MIN_OA)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### VLV-1 — Cooling valve leakage

```python
FAULT_CONFIRM_SECONDS = 900
clg = norm_cmd(d["clg_valve_pct"])
mask = (
    d["sat"].notna() & d["sat_sp"].notna()
    & (clg <= 0.05) & (d["sat"] < d["sat_sp"] - 2.0)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### DMP-1 — OA damper leakage

```python
FAULT_CONFIRM_SECONDS = 900
LEAK_DELTA = 2.0
damper = norm_cmd(d["oa_damper_pct"])
mask = (
    d["oa_t"].notna() & d["mat"].notna()
    & (damper <= 0.05) & (d["mat"].sub(d["oa_t"]).abs() < LEAK_DELTA)
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### VAV-5 — Airflow sensor bias

```python
FAULT_CONFIRM_SECONDS = 900
damper = norm_cmd(v["damper_pct"])
mask = v["zone_flow"].notna() & (v["zone_flow"] > 50.0) & (damper < 0.10)
v = apply_fault(v, mask)
v["fault_confirmed"] = confirm_fault(v["fault_raw"])
```

### PLANT-1 — CHW DP reset missing

```python
FAULT_CONFIRM_SECONDS = 900
pump = norm_cmd(p["chw_pump_cmd"])
mask = (
    p["chw_dp_sp"].notna() & p["chw_load_pct"].notna()
    & (pump > 0.01) & (p["chw_load_pct"] < 0.40) & (p["chw_dp_sp"] > 18.0)
)
p = apply_fault(p, mask)
p["fault_confirmed"] = confirm_fault(p["fault_raw"])
```

### SP-HIGH — Occupied setpoint too high

```python
FAULT_CONFIRM_SECONDS = 900
mask = (
    v["zone_t_sp"].notna() & v["occ_mode"].eq("occupied") & (v["zone_t_sp"] > 76.0)
)
v = apply_fault(v, mask)
v["fault_confirmed"] = confirm_fault(v["fault_raw"])
```

### SP-LOW — Occupied setpoint too low

```python
FAULT_CONFIRM_SECONDS = 900
mask = (
    v["zone_t_sp"].notna() & v["occ_mode"].eq("occupied") & (v["zone_t_sp"] < 68.0)
)
v = apply_fault(v, mask)
v["fault_confirmed"] = confirm_fault(v["fault_raw"])
```

### KPI-1 — Performance score (advisory)

```python
# Roll up confirmed fault counts by taxonomy family over 7 days — advisory only.
# See benchmark-strategy.md for weight defaults.
```

---

## Extended rule families (P2)

Mirrors [SQL P2 section](datafusion-sql-cookbook.html#extended-rule-families-p2).

### VAV-6 — Reheat when cooling available

```python
FAULT_CONFIRM_SECONDS = 300
reheat = norm_cmd(v["reheat_valve_pct"])
mask = (
    v.get("clg_available", False).astype(bool)
    & v["oa_t"].notna() & (v["oa_t"] < 65.0) & (reheat > 0.25)
)
v = apply_fault(v, mask)
v["fault_confirmed"] = confirm_fault(v["fault_raw"])
```

### VAV-7 — Minimum airflow violation

```python
FAULT_CONFIRM_SECONDS = 900
fan = norm_cmd(v["fan_cmd"]) if "fan_cmd" in v else 1.0
mask = (
    v["zone_flow"].notna() & v["min_flow_sp"].notna()
    & (fan > 0.01) & (v["zone_flow"] < v["min_flow_sp"])
)
v = apply_fault(v, mask)
v["fault_confirmed"] = confirm_fault(v["fault_raw"])
```

### TOWER-1 — Cooling tower approach high

```python
FAULT_CONFIRM_SECONDS = 900
MAX_APPROACH = 7.0
t = df[df["equipment_id"] == "equip:your-cooling-tower"].copy()
fan = norm_cmd(t["tower_fan_cmd"])
mask = (
    t["tower_leaving_t"].notna() & t["wb_t"].notna()
    & (fan > 0.01) & ((t["tower_leaving_t"] - t["wb_t"]) > MAX_APPROACH)
)
t = apply_fault(t, mask)
t["fault_confirmed"] = confirm_fault(t["fault_raw"])
```

### CTRL-2 — Generic control loop hunting

```python
FAULT_CONFIRM_SECONDS = 3600
HUNT_REVERSALS = 8
ROLL = 60  # samples ~1 h @ 60 s poll

s = d["duct_static"].diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
reversals = (s != s.shift(1)) & (s != 0)
mask = reversals.rolling(ROLL, min_periods=ROLL).sum() > HUNT_REVERSALS
d = apply_fault(d, mask.fillna(False))
d["fault_confirmed"] = confirm_fault(d["fault_raw"], min_rows=FAULT_CONFIRM_SECONDS // POLL_SECONDS)
```

### PID-HUNT-1 — Suspected control-output hunting

**Distinct from FC4** (mode transitions) and **CTRL-2** (process-variable reversals). Measures rolling 1h **total variation** of a 0–100% control output. UI: “Suspected control-loop hunting.”

Deep dive + defaults: [PID-HUNT-1](pid-hunt-1.html) · gates: [operational-gates](operational-gates.html).

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PidHuntingParams:
    window: str = "1h"
    resample_interval: str = "1min"
    max_fill_intervals: int = 10
    change_deadband_pct: float = 1.0
    minimum_span_pct: float = 20.0
    total_variation_fault_pct: float = 500.0
    minimum_equivalent_cycles: float = 2.5
    minimum_reversals: int = 4
    minimum_coverage_pct: float = 80.0


def calculate_pid_hunting(
    df: pd.DataFrame,
    *,
    timestamp_col: str = "timestamp",
    value_col: str = "control_output_pct",
    group_cols: tuple[str, ...] = ("equipment_id", "point_id"),
    enable_col: str | None = None,
    params: PidHuntingParams = PidHuntingParams(),
) -> pd.DataFrame:
    """Rolling one-hour control-output hunting metrics (oracle / parity)."""
    required = {timestamp_col, value_col, *group_cols}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    work = df.copy()
    work[timestamp_col] = pd.to_datetime(work[timestamp_col], utc=True, errors="coerce")
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    work = work.dropna(subset=[timestamp_col, value_col])
    finite = work[value_col]
    if not finite.empty and float(finite.quantile(0.95)) <= 1.5:
        work[value_col] = work[value_col] * 100.0
    work[value_col] = work[value_col].clip(lower=0.0, upper=100.0)

    interval = pd.Timedelta(params.resample_interval)
    window = pd.Timedelta(params.window)
    expected_samples = max(2, int(window / interval))
    minimum_samples = max(
        2, int(np.ceil(expected_samples * params.minimum_coverage_pct / 100.0))
    )

    def evaluate_group(group: pd.DataFrame) -> pd.DataFrame:
        group = group.sort_values(timestamp_col).set_index(timestamp_col)
        output = group[value_col].resample(params.resample_interval).mean()
        output = output.ffill(limit=params.max_fill_intervals)
        valid = output.notna()
        raw_delta = output.diff()
        significant_delta = raw_delta.where(
            raw_delta.abs() >= params.change_deadband_pct, 0.0
        )
        total_variation = significant_delta.abs().rolling(
            params.window, min_periods=minimum_samples
        ).sum()
        rolling_min = output.rolling(params.window, min_periods=minimum_samples).min()
        rolling_max = output.rolling(params.window, min_periods=minimum_samples).max()
        output_span = rolling_max - rolling_min
        direction = pd.Series(
            np.sign(significant_delta), index=significant_delta.index, dtype="float64"
        ).replace(0.0, np.nan)
        previous_direction = direction.ffill().shift(1)
        reversal_event = (
            direction.notna()
            & previous_direction.notna()
            & direction.ne(previous_direction)
        ).astype("int64")
        reversals = reversal_event.rolling(
            params.window, min_periods=minimum_samples
        ).sum()
        valid_samples = valid.astype("int64").rolling(params.window, min_periods=1).sum()
        coverage_pct = (100.0 * valid_samples / float(expected_samples)).clip(upper=100.0)
        equivalent_cycles = total_variation / (2.0 * output_span.replace(0.0, np.nan))
        enabled = pd.Series(True, index=output.index)
        if enable_col and enable_col in group.columns:
            enabled = (
                pd.to_numeric(group[enable_col], errors="coerce")
                .resample(params.resample_interval)
                .max()
                .ffill(limit=params.max_fill_intervals)
                .fillna(0)
                .gt(0)
            )
        fault = (
            enabled
            & coverage_pct.ge(params.minimum_coverage_pct)
            & output_span.ge(params.minimum_span_pct)
            & total_variation.ge(params.total_variation_fault_pct)
            & equivalent_cycles.ge(params.minimum_equivalent_cycles)
            & reversals.ge(params.minimum_reversals)
        )
        result = pd.DataFrame(
            {
                "control_output_pct": output,
                "total_variation_1h": total_variation,
                "output_span_1h": output_span,
                "equivalent_cycles_1h": equivalent_cycles,
                "reversals_1h": reversals,
                "coverage_pct_1h": coverage_pct,
                "loop_enabled": enabled,
                "fault": fault.fillna(False),
            }
        )
        result["status"] = np.select(
            [
                result["coverage_pct_1h"].lt(params.minimum_coverage_pct),
                ~result["loop_enabled"],
                result["fault"],
            ],
            ["SKIPPED_INSUFFICIENT_DATA", "SKIPPED_EQUIPMENT_OFF", "FAULT"],
            default="PASS",
        )
        return result.reset_index()

    results: list[pd.DataFrame] = []
    group_key = list(group_cols) if len(group_cols) > 1 else group_cols[0]
    for key, group in work.groupby(group_key, dropna=False, sort=False):
        evaluated = evaluate_group(group)
        key_values = key if isinstance(key, tuple) else (key,)
        for column, value in zip(group_cols, key_values, strict=True):
            evaluated[column] = value
        results.append(evaluated)
    if not results:
        return pd.DataFrame()
    return pd.concat(results, ignore_index=True)


# Example (expect last row ~ TV=500, span=100, cycles=2.5, FAULT):
# example = pd.DataFrame({
#     "timestamp": pd.date_range("2026-07-10 08:00", periods=6, freq="12min", tz="UTC"),
#     "equipment_id": "AHU_1",
#     "point_id": "duct_static_pid_output",
#     "control_output_pct": [0, 100, 0, 100, 0, 100],
# })
# calculate_pid_hunting(example, params=PidHuntingParams(resample_interval="12min", max_fill_intervals=1))
```

SQL parity: [DataFusion PID-HUNT-1](datafusion-sql-cookbook.html#pid-hunt-1--suspected-control-output-hunting) · `sql_rules/pid_hunt_1.sql`.

### SV-7 — Wrong-units heuristic

```python
FAULT_CONFIRM_SECONDS = 300
mask = d["oa_t"].notna() & ((d["oa_t"] > 200.0) | (d["oa_t"] < -60.0))
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

### OA-2 — DCV minimum OA not met

```python
FAULT_CONFIRM_SECONDS = 900
mask = (
    d["oa_flow"].notna() & d["oa_flow_min_sp"].notna()
    & d["occ_mode"].eq("occupied") & d["fan_status"].astype(bool)
    & (d["oa_flow"] < d["oa_flow_min_sp"])
)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
```

---

## Framework docs

| Doc | Purpose |
|-----|---------|
| [Taxonomy](taxonomy.html) | Public fault taxonomy |
| [Rule schema](rule-schema.html) | Metadata source of truth |
| [Gap matrix](gap-matrix.html) | Literature coverage |
| [Parity matrix](parity-matrix.html) | SQL ↔ Pandas audit |
| [Roadmap](roadmap.html) | Expansion priorities |
| [Prerequisite macros](prerequisite-macros.html) | Shared guards |
| [Operational gates](operational-gates.html) | RUN / CONDITIONAL / ALWAYS |
| [PID-HUNT-1](pid-hunt-1.html) | Control-output total-variation hunting |
| [Benchmark strategy](benchmark-strategy.html) | Validation scenarios |
| [Doc template](doc-template.html) | Per-rule standard |

---

## Export to Open-FDD SQL

After validating in Pandas, port the boolean expression to DataFusion SQL for production on the edge:

| Pandas | DataFusion SQL |
|--------|----------------|
| `s.notna()` | `col IS NOT NULL` |
| `a & b` | `a AND b` |
| `a \| b` | `a OR b` |
| `~a` | `NOT a` |
| `s.abs()` | `ABS(col)` |
| `np.minimum(a,b)` | `LEAST(a,b)` |
| `np.maximum(a,b)` | `GREATEST(a,b)` |
| `FAULT_CONFIRM_SECONDS = 300` | `"confirmation_seconds": 300` in API |

Test SQL with `POST /api/fdd-rules/{id}/test-sql` before activate.

---

**Next:** [DataFusion SQL cookbook](datafusion-sql-cookbook.html) — edge runtime rules for Open-FDD
