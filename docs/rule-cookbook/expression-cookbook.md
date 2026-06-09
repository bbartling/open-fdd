---
title: Expression cookbook (Arrow-native)
parent: Rule Cookbook
nav_order: 0
---

# Expression cookbook (Arrow-native)

Reference for **Open-FDD 3.x Rule Lab**: every rule is a Python module with **`apply_faults_arrow(table, cfg, context)`** using **`pyarrow.compute`** — **no pandas**, **no YAML expression files**, **no NumPy DataFrames on the IoT edge**.

This page **replaces the legacy pandas `type: expression` YAML cookbook**. Each legacy recipe maps to a **fixed [fault code](../fault-codes/)** and an Arrow pattern below.

| Topic | Page |
|-------|------|
| Quick templates | [Arrow recipes](arrow-recipes) |
| Shared imports | [Python recipes](python-recipes) |
| Console window stats | [Lookback window](lookback-window) |
| Fault code catalog | [Fault codes](../fault-codes/) |
| Programmatic defaults | `open_fdd.arrow_runtime.sensor_catalog` |

---

## Legacy → modern translation

| Legacy (pandas / YAML) | Arrow-native (3.x) |
|------------------------|---------------------|
| `type: expression` + `expression:` string | `apply_faults_arrow()` in `rules_py/*.py` |
| `RuleRunner.run(df, column_map=…)` | Rule Lab batch on **feather PyArrow table** |
| `np.maximum(a, b)` | `pc.max(a, b)` |
| `series.rolling(n).min()` | `arrow_rolling_min(vals, n)` from `open_fdd.arrow_runtime.windows` |
| `series.diff().abs()` | `arrow_abs_diff(vals, 1)` |
| `normalize_cmd(x)` | `pc.if_else(pc.greater(x, 1), pc.divide(x, 100), x)` |
| `params.max_temp` in YAML | Module constant or `cfg["bounds_high"]` |
| `flag: rule_a_flag` | Rule metadata **`fault_code`** → `AHU-A` … `VAV-C` |
| Numeric codes `VAV-03` | Letter codes **`VAV-C`** (see `LEGACY_CODE_MAP` in bridge) |

**Edge constraint:** Docker / BACnet poll path never imports pandas. Central portfolio Dash may use pandas for CSV analytics only.

---

## How Arrow rules are structured

1. **Historian columns** — Feather column names from BACnet poll (`oa-t`, `sa-t`, `stat_zn-t`, …) or Brick labels via model export.
2. **Module constants** — Thresholds at top of file (bench style) or read from `cfg` for site tuning.
3. **`apply_faults_arrow`** — Returns a **boolean PyArrow array** (True = fault sample).
4. **`fault_code`** — Set in Rule Lab metadata; must exist in `GET /api/faults/catalog`.

```python
import pyarrow.compute as pc
from open_fdd.arrow_runtime.cookbook import sensor_bounds_mask

FAULT_CODE = "VAV-C"  # metadata in Rule Lab UI


def apply_faults_arrow(table, cfg, context=None):
    return sensor_bounds_mask(table, "zone_temp", cfg)
```

### Command scaling (0–1 vs 0–100 %)

BACnet often exposes **0–100** for damper/VFD commands. Scale explicitly:

```python
def _norm_cmd(col):
    return pc.if_else(pc.greater(col, 1.0), pc.divide(col, 100.0), col)
```

### Occupied hours (schedule gating)

Use `open_fdd.arrow_runtime.cookbook._unoccupied_mask` or compare local hour from `timestamp` column. Example: **fan on when unoccupied** → **BLD-C** / `schedule_compare`.

---

## Sensor validation (bounds, flatline, rate of change)

Use **`open_fdd.arrow_runtime.sensor_catalog.SENSOR_PROFILES`** for defaults, or copy constants into `rules_py`. Tune per site in Rule Lab `cfg` or building-agent tuning brief.

### Bounds (out of range) — `oob_rolling`

| Sensor kind | Min | Max | Flatline tol | Max Δ / hour | Max Δ / 15 min | Typical fault code |
|-------------|-----|-----|--------------|--------------|----------------|-------------------|
| Zone temp (°F) | 55 | 90 | 0.10 | 4.0 | 2.0 | **VAV-C** |
| Supply air temp | 50 | 110 | 0.15 | 8.0 | 3.0 | **AHU-C**, **RTU-C** |
| Return air temp | 55 | 95 | 0.10 | 3.0 | 1.5 | **AHU-D** (also mixing) |
| Mixed air temp | 40 | 110 | 0.15 | 6.0 | 2.5 | **AHU-D** |
| Outdoor air temp | −40 | 130 | 0.10 | 12.0 | 6.0 | **BLD-B** |
| Duct static (inH₂O) | −0.5 | 3.0 | 0.02 | 0.5 | 0.25 | **AHU-A** |
| Relative humidity (%) | 0 | 100 | 1.0 | 15.0 | 8.0 | **DC-C** |
| Chilled water (°F) | 40 | 90 | 0.10 | 4.0 | 2.0 | **CH-D** |
| Hot water (°F) | 70 | 200 | 0.15 | 6.0 | 3.0 | **CH-D** |
| Condenser water (°F) | 50 | 110 | 0.15 | 5.0 | 2.5 | **CH-A** |
| CO₂ (ppm, occupied) | 400 | 1000 | 5.0 | 200 | 80 | **VAV-B** (ventilation) |
| Discharge air temp | 45 | 120 | 0.15 | 10.0 | 4.0 | **VAV-E**, **HP-D** |

**Return air** uses a **narrow band** vs zone/OAT because RAT should track building return conditions, not outdoor extremes. When OAT/RAT/MAT are all present, prefer **mixing envelope** (below) over RAT bounds alone.

**CO₂ upper bound** is an occupied ventilation target; unoccupied rules may use 400–2000 ppm per policy.

### Flatline (stuck sensor) — `flatline_1h`

Default **12 samples ≈ 1 hour** at 5-minute poll. True when rolling max − min ≤ tolerance.

```python
from open_fdd.arrow_runtime.cookbook import sensor_flatline_mask

def apply_faults_arrow(table, cfg, context=None):
    return sensor_flatline_mask(table, "outdoor_air_temp", cfg)  # BLD-B
```

Bench references: `workspace/data/rules_py/bench_oa-t_flatline_1h.py`, `bench_stat_zn-t_flatline_1h.py`.

### Rate of change (spike) — `rate_of_change`

Flags physically impossible step changes (comms glitch, substituted value).

```python
from open_fdd.arrow_runtime.cookbook import rate_of_change_mask
from open_fdd.arrow_runtime.sensor_catalog import cfg_from_profile

def apply_faults_arrow(table, cfg, context=None):
    merged = cfg_from_profile("outdoor_air_temp", cfg)
    merged["samples_per_hour"] = 12  # 5-min poll
    return rate_of_change_mask(table, merged, col="oa-t")
```

Legacy **weather_temp_spike** (`spike_limit: 16` °F per step) → **BLD-B** with `max_per_15min: 6` or stricter per-step limit.

### Mixing envelope (MAT vs OAT/RAT) — `mixing_envelope`

Legacy GL36 **Rule B / C** and **AHU-D**. MAT should sit between OAT and RAT (± tolerance) while fan runs.

```python
from open_fdd.arrow_runtime.cookbook import mixing_envelope_mask

def apply_faults_arrow(table, cfg, context=None):
    return mixing_envelope_mask(
        table,
        {**cfg, "mixing_tol": 1.15},
        mat_col="ma-t",
        oat_col="oa-t",
        rat_col="ra-t",
        fan_col="supply-fan-speed-command",
    )
```

---

## GL36-inspired AHU rules (legacy expression → fault code)

ASHRAE Guideline 36-style rules from the old YAML cookbook, translated to Arrow. Assign **`fault_code`** per row in Rule Lab.

| Legacy rule | Summary | Suggested code | Pattern |
|-------------|---------|----------------|---------|
| Rule A — duct static low @ full fan | SP below SP setpoint at high VFD | **AHU-A** | `custom_arrow` |
| Rule B — blend below band | MAT below OAT/RAT envelope | **AHU-D** | `mixing_envelope` |
| Rule C — blend above band | MAT above OAT/RAT envelope | **AHU-D** | `mixing_envelope` |
| Rule D — discharge cold when heating | SAT low vs MAT, heat valve open | **AHU-B** | `custom_arrow` |
| Rule E — SAT low, full heating | SAT below SP, valve > 90% | **AHU-C** / performance | `custom_arrow` |
| Rule F — SAT/MAT mismatch econ | Econ mode, SAT ≠ MAT | **AHU-E** | `custom_arrow` |
| Rule G — ambient warm free cool | OAT > SAT SP, econ open, cool off | **AHU-E** | `custom_arrow` |
| Rule H — OAT/MAT mismatch econ+mech | Mech + econ, MAT ≠ OAT | **AHU-E** | `mixing_envelope` |
| Rule I — OAT/MAT mismatch econ-only | Econ only, MAT ≠ OAT | **AHU-E** | `mixing_envelope` |
| Rule J — discharge above blend cooling | SAT > MAT in cooling | **AHU-B** | `custom_arrow` |
| Rule K — discharge above SP full cool | SAT > SP, full cooling | **AHU-C** | `custom_arrow` |
| Rule L — cooling coil ΔT when off | CHW drop when valves closed | **CH-C** | `custom_arrow` |
| Rule M — heating coil ΔT when off | HW rise when valves closed | **AHU-B** | `custom_arrow` |

### Rule A — duct static low at full speed (Arrow sketch)

```python
import pyarrow.compute as pc

SP = "duct-static-pressure"
SP_SP = "duct-static-pressure-sp"
FAN = "supply-fan-speed-command"
SP_MARGIN = 0.12
DRV_HI = 0.93


def apply_faults_arrow(table, cfg, context=None):
    sp = pc.cast(table[SP], "float64")
    sp_sp = pc.cast(table[SP_SP], "float64")
    fan = pc.if_else(pc.greater(table[FAN], 1), pc.divide(table[FAN], 100), table[FAN])
    low_sp = pc.less(sp, pc.subtract(sp_sp, SP_MARGIN))
    fan_hi = pc.greater_equal(fan, DRV_HI - 0.06)
    return pc.and_(low_sp, fan_hi)
```

---

## Starter pack (VAV / AHU baseline)

Maps to legacy YAML starter filenames; use as first deploy bundle.

| Legacy YAML starter | Arrow approach | Fault code |
|---------------------|----------------|------------|
| `01_vav_zone_temp_bounds_occupied` | `sensor_bounds_mask(..., "zone_temp")` + occupied mask | **VAV-C** |
| `02_vav_zone_temp_flatline_occupied` | `sensor_flatline_mask(..., "zone_temp")` + occupied | **VAV-C** |
| `03_vav_damper_command_extreme_flatline` | `flatline_1h_mask` on damper cmd column | **VAV-D** |
| `04_ahu_runtime_outside_schedule` | `after_hours_fan_satisfied_mask` / run-hours script | **BLD-C** |
| `05_ahu_duct_static_pressure_not_maintained` | Rule A sketch above | **AHU-A** |
| `06_ahu_internal_temp_sensor_bounds` | `sensor_bounds_mask` on SAT/MAT | **AHU-C** |
| `07_ahu_internal_temp_sensor_flatline` | `sensor_flatline_mask` on SAT | **AHU-C** |

### Economizer starters

| Legacy name | Fault code | Key logic |
|-------------|------------|-----------|
| `ahu_econ_100oa_temp_tracking_fault` | **AHU-E** | OA damper ≥ 95%, \|MAT−OAT\| and \|SAT−MAT\| > tol |
| `ahu_mech_cooling_when_free_cooling_available` | **AHU-E** | OAT ≤ SAT SP − margin, low OA damper, cooling valve on |
| `ahu_oa_damper_excess_open_extreme_ambient` | **AHU-E** | OA ≥ 50% when OAT > 70 °F or OAT < 40 °F |

---

## VAV, central plant, heat pump

| Legacy recipe | Fault code | Notes |
|---------------|------------|-------|
| `zone_reheat_warm_ambient` | **VAV-A** | Reheat open when OAT > cutoff |
| `zone_damper_valve_full_open` | **VAV-D** | Damper > 97.5% for rolling window |
| `dp_below_sp_pump_max` | **CH-E** | Plant DP low at max pump speed |
| `flow_high_pump_max` | **CH-B** | High flow at max pump |
| `plant_supply_temp_deadband` | **CH-D** | CHW SP ± band while pump on |
| `chiller_excessive_runtime` | **CH-F** | Rolling sum of chiller on samples |
| `hp_discharge_cold_when_heating` | **HP-D** | SAT low, zone cold, fan on |

Rolling persistence in pandas `.rolling(n).min()` → `arrow_rolling_min` + `pc.and_` with current sample.

---

## Opportunistic / ventilation

| Legacy recipe | Fault code |
|---------------|------------|
| `econ_active_warm_ambient` | **AHU-E** |
| `mech_cool_when_econ_available` | **AHU-E** |
| `low_oa_fraction_estimated` | **VAV-B** / **BLD-A** |
| `preheat_excess_temp` | **AHU-B** |
| `weather_temp_spike` | **BLD-B** (`rate_of_change`) |
| `weather_gust_lt_wind` | **BLD-B** (custom compare) |

**OA fraction estimate** (no airflow meter):

```python
# Guard: |RAT - OAT| > gap before dividing
oa_frac = (mat - rat) / (oat - rat) * 100
# Flag when oa_frac < oa_min_pct and fan on
```

Use `pc.and_` with gap check; skip divide where denominator near zero.

---

## Data quality vs equipment faults

| Symptom | Pattern | Code | Do not confuse with |
|---------|---------|------|---------------------|
| Flatline 1 h | `flatline_1h` | **VAV-C**, **AHU-C**, **BLD-B** | Equipment off / damper closed |
| OOB sample | `oob_rolling` | sensor-specific | True process excursion |
| Spike between polls | `rate_of_change` | **BLD-B** | Fast legitimate weather front |
| No new samples | `stale_points` | **BLD-D** | Equipment fault |
| MAT ∉ [OAT, RAT] | `mixing_envelope` | **AHU-D** | Stratification during startup |

Always gate sensor faults with **fan on**, **valve open**, or **occupied** where appropriate — see [Sensor & data quality](../fault-codes/sensor-quality).

---

## Metric (°C) equivalents

Set `cfg["temp_unit"] = "metric"` in Rule Lab or scale constants:

| Imperial | Metric (approx) |
|----------|-----------------|
| 55 °F | 12.8 °C |
| 90 °F | 32.2 °C |
| 50 °F | 10.0 °C |
| 110 °F | 43.3 °C |
| 2.0 °F tol | 1.1 °C |
| 0.15 inH₂O | ~37 Pa |

`open_fdd.playground.temp_units` documents UI field keys for °F/°C toggle.

---

## Binding rules to the fault catalog

1. Pick a **letter code** from [Fault codes](../fault-codes/) — never invent suffixes.
2. In Rule Lab, set **fault_code** on the rule row.
3. Batch FDD aggregates into `GET /api/faults/status` and portfolio rollup.
4. Legacy numeric codes (`AHU-03`) migrate via `LEGACY_CODE_MAP` in the bridge.

```bash
curl -s http://127.0.0.1:8765/api/faults/catalog | jq '.families[].codes[] | select(.code=="VAV-C")'
```

---

## Pandas YAML → Arrow checklist (commissioning)

- [ ] Replace each `type: expression` YAML with a `rules_py` module
- [ ] Map `inputs` Brick labels → feather column names in model/poll CSV
- [ ] Set `fault_code` per rule (letter suffix)
- [ ] Run Rule Lab kit on 7-day feather window; confirm flag rate sane
- [ ] Apply sensor_catalog defaults; tune bounds for site climate
- [ ] Enable building-agent check-in; verify faults in portfolio rollup

**Next:** [Arrow recipes](arrow-recipes) · [Fault codes](../fault-codes/) · [Rule Lab](../operator-bridge/rule-lab)
