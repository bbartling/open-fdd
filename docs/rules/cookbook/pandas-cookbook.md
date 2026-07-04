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
7. [Central plants](#central-plants)
8. [Heat pumps](#heat-pumps)
9. [Weather station](#weather-station)
10. [Trim & respond advisory](#trim--respond-advisory)
11. [Export to Open-FDD SQL](#export-to-open-fdd-sql)

---

## Setup & shared helpers

```python
import pandas as pd
import numpy as np

# Wide historian export (one row per timestamp × equipment)
df = pd.read_json("telemetry_pivot.jsonl", lines=True)
# Or: df = pd.read_feather("telemetry_pivot.feather")

df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
df = df.sort_values(["equipment_id", "timestamp"])

EQUIP = "equip:your-ahu"
d = df[df["equipment_id"] == EQUIP].copy()
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

### SV-4 — Flatline (stuck sensor)

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

### SV-5 — Rate-of-change spike

```python
FAULT_CONFIRM_SECONDS = 300
SPIKE_LIMIT = 16.0  # °F per sample

mask = d["oa_t"].notna() & (d["oa_t"].diff().abs() > SPIKE_LIMIT)
d = apply_fault(d, mask)
d["fault_confirmed"] = confirm_fault(d["fault_raw"])
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
