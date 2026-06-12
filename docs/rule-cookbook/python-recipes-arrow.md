---
title: Python recipes (full Arrow library)
parent: Rule Cookbook
nav_order: 0
---

# Python recipes — full Arrow library

Copy-paste **`apply_faults_arrow`** modules for Rule Lab. Replaces the legacy pandas/YAML Expression Rule Cookbook.

- **No pandas** on the edge — PyArrow + `pyarrow.compute` only
- Set **`fault_code`** in Rule Lab metadata (letter codes or Grade-A `AHU-ECON-001`)
- Map historian column names in the data model / rule bindings (`ma-t`, `oa-t`, `stat_zn-t`, …)

Quick patterns: [Arrow recipes]({{ "/rule-cookbook/arrow-recipes/" | relative_url }}) · Index: [Expression cookbook (Arrow-native)]({{ "/rule-cookbook/expression-cookbook/" | relative_url }})

---

## Shared helpers (paste once per rule file)

```python
import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime.cookbook import mixing_envelope_mask
from open_fdd.arrow_runtime.windows import (
    arrow_rolling_min,
    arrow_rolling_max,
    arrow_abs_diff,
)


def _norm_cmd(col: pa.ChunkedArray) -> pa.ChunkedArray:
    c = pc.cast(col, pa.float64())
    return pc.if_else(pc.greater(c, 1.0), pc.divide(c, 100.0), c)


def _col(table, name: str) -> pa.ChunkedArray:
    return pc.cast(table[name], pa.float64())


def _hypot_tol(a: float, b: float) -> float:
    return (a * a + b * b) ** 0.5
```

---

## GL36 AHU Rules A–M

### Rule A — duct static low at full fan speed (`AHU-A`)

```python
FAULT_CODE = "AHU-A"
SP, SP_SP, FAN = "duct-static-pressure", "duct-static-pressure-sp", "supply-fan-speed-command"
SP_MARGIN, DRV_HI, DRV_NEAR = 0.12, 0.93, 0.06


def apply_faults_arrow(table, cfg, context=None):
    sp, sp_sp = _col(table, SP), _col(table, SP_SP)
    fan = _norm_cmd(table[FAN])
    return pc.and_(
        pc.less(sp, pc.subtract(sp_sp, SP_MARGIN)),
        pc.greater_equal(fan, DRV_HI - DRV_NEAR),
    )
```

### Rules B & C — blended air outside OAT/RAT band (`AHU-D`)

Uses `mixing_envelope_mask` (covers below-band and above-band).

```python
FAULT_CODE = "AHU-D"


def apply_faults_arrow(table, cfg, context=None):
    return mixing_envelope_mask(
        table,
        {**cfg, "mixing_tol": 1.15, "normalize_cmd_percent": 1},
        mat_col="ma-t",
        oat_col="oa-t",
        rat_col="ra-t",
        fan_col="supply-fan-speed-command",
    )
```

### Rule D — discharge cold when heating commanded (`AHU-B`)

```python
FAULT_CODE = "AHU-B"
BLEND_TOL, SAT_TOL, FAN_DT = 1.15, 1.15, 0.55


def apply_faults_arrow(table, cfg, context=None):
    mat, sat = _col(table, "ma-t"), _col(table, "sa-t")
    valve = _norm_cmd(table["heating-valve-command"])
    fan = _norm_cmd(table["supply-fan-speed-command"])
    rhs = pc.add(pc.subtract(mat, BLEND_TOL), FAN_DT)
    cold = pc.less_equal(pc.add(sat, SAT_TOL), rhs)
    return pc.and_(cold, pc.greater(valve, 0.01), pc.greater(fan, 0.01))
```

### Rule E — SAT too low with full heating (`AHU-C`)

```python
FAULT_CODE = "AHU-C"
SUPPLY_ERR = 1.0


def apply_faults_arrow(table, cfg, context=None):
    sat = _col(table, "sa-t")
    sp = _col(table, "sa-t-sp") if "sa-t-sp" in table.column_names else _col(table, "supply-air-temperature-setpoint")
    valve = _norm_cmd(table["heating-valve-command"])
    fan = _norm_cmd(table["supply-fan-speed-command"])
    return pc.and_(
        pc.less(sat, pc.subtract(sp, SUPPLY_ERR)),
        pc.greater(valve, 0.9),
        pc.greater(fan, 0.01),
    )
```

### Rule F — SAT/MAT mismatch in economizer mode (`AHU-E`)

```python
FAULT_CODE = "AHU-E"
FAN_DT, BLEND_TOL, SAT_TOL, ECON_MIN = 0.55, 1.15, 1.15, 0.12
TOL = _hypot_tol(SAT_TOL, BLEND_TOL)


def apply_faults_arrow(table, cfg, context=None):
    mat, sat = _col(table, "ma-t"), _col(table, "sa-t")
    damper = _norm_cmd(table["oa-damper-command"])
    cool = _norm_cmd(table["cooling-valve-command"])
    mismatch = pc.greater(pc.abs(pc.subtract(pc.subtract(sat, FAN_DT), mat)), TOL)
    econ = pc.and_(pc.greater(damper, ECON_MIN), pc.less(cool, 0.1))
    return pc.and_(mismatch, econ)
```

### Rule G — ambient too warm for free cooling (`AHU-E`)

```python
FAULT_CODE = "AHU-E"
OAT_TOL, FAN_DT, SAT_TOL, ECON_MIN = 1.15, 0.55, 1.15, 0.12


def apply_faults_arrow(table, cfg, context=None):
    oat = _col(table, "oa-t")
    sp = _col(table, "sa-t-sp")
    damper = _norm_cmd(table["oa-damper-command"])
    cool = _norm_cmd(table["cooling-valve-command"])
    warm = pc.greater(oat, pc.add(pc.subtract(sp, FAN_DT), SAT_TOL - OAT_TOL))
    econ = pc.and_(pc.greater(damper, ECON_MIN), pc.less(cool, 0.1))
    return pc.and_(warm, econ)
```

### Rule H — OAT/MAT mismatch (econ + mech cooling) (`AHU-E`)

```python
FAULT_CODE = "AHU-E"
OAT_TOL, BLEND_TOL = 1.15, 1.15
TOL = _hypot_tol(OAT_TOL, BLEND_TOL)


def apply_faults_arrow(table, cfg, context=None):
    oat, mat = _col(table, "oa-t"), _col(table, "ma-t")
    cool = _norm_cmd(table["cooling-valve-command"])
    damper = _norm_cmd(table["oa-damper-command"])
    return pc.and_(
        pc.greater(pc.abs(pc.subtract(mat, oat)), TOL),
        pc.greater(cool, 0.01),
        pc.greater(damper, 0.9),
    )
```

### Rule I — OAT/MAT mismatch (economizer only) (`AHU-E`)

```python
FAULT_CODE = "AHU-E"
TOL = _hypot_tol(1.15, 1.15)


def apply_faults_arrow(table, cfg, context=None):
    oat, mat = _col(table, "oa-t"), _col(table, "ma-t")
    damper = _norm_cmd(table["oa-damper-command"])
    return pc.and_(pc.greater(pc.abs(pc.subtract(mat, oat)), TOL), pc.greater(damper, 0.9))
```

### Rule J — discharge above blended in cooling (`AHU-B`)

```python
FAULT_CODE = "AHU-B"
FAN_DT, BLEND_TOL, SAT_TOL, ECON_MIN = 0.55, 1.15, 1.15, 0.12
TOL = _hypot_tol(SAT_TOL, BLEND_TOL)


def apply_faults_arrow(table, cfg, context=None):
    sat, mat = _col(table, "sa-t"), _col(table, "ma-t")
    cool = _norm_cmd(table["cooling-valve-command"])
    damper = _norm_cmd(table["oa-damper-command"])
    hot = pc.greater(sat, pc.add(mat, pc.add(TOL, FAN_DT)))
    mode_a = pc.and_(pc.greater(damper, 0.9), pc.greater(cool, 0.0))
    mode_b = pc.and_(pc.less_equal(damper, ECON_MIN), pc.greater(cool, 0.9))
    return pc.and_(hot, pc.or_(mode_a, mode_b))
```

### Rule K — discharge above setpoint in full cooling (`AHU-C`)

```python
FAULT_CODE = "AHU-C"
SAT_TOL, ECON_MIN = 1.15, 0.12


def apply_faults_arrow(table, cfg, context=None):
    sat = _col(table, "sa-t")
    sp = _col(table, "sa-t-sp")
    cool = _norm_cmd(table["cooling-valve-command"])
    damper = _norm_cmd(table["oa-damper-command"])
    high = pc.greater(sat, pc.add(sp, SAT_TOL))
    full = pc.or_(
        pc.and_(pc.greater(damper, 0.9), pc.greater(cool, 0.9)),
        pc.and_(pc.less_equal(damper, ECON_MIN), pc.greater(cool, 0.9)),
    )
    return pc.and_(high, full)
```

### Rule L — cooling coil ΔT when inactive (`CH-C`)

```python
FAULT_CODE = "CH-C"
ENTER_TOL, LEAVE_TOL, ECON_MIN = 1.15, 1.15, 0.12
TOL = _hypot_tol(ENTER_TOL, LEAVE_TOL)


def apply_faults_arrow(table, cfg, context=None):
    ent = _col(table, "cooling-coil-entering-air-temperature")
    leave = _col(table, "cooling-coil-leaving-air-temperature")
    heat = _norm_cmd(table["heating-valve-command"])
    cool = _norm_cmd(table["cooling-valve-command"])
    damper = _norm_cmd(table["oa-damper-command"])
    drop = pc.greater(pc.subtract(ent, leave), TOL)
    mode_a = pc.and_(pc.greater(heat, 0), pc.equal(cool, 0), pc.less_equal(damper, ECON_MIN))
    mode_b = pc.and_(pc.equal(heat, 0), pc.equal(cool, 0), pc.greater(damper, ECON_MIN))
    return pc.and_(drop, pc.or_(mode_a, mode_b))
```

### Rule M — heating coil ΔT when inactive (`AHU-B`)

```python
FAULT_CODE = "AHU-B"
ENTER_TOL, LEAVE_TOL, FAN_DT, ECON_MIN = 1.15, 1.15, 0.55, 0.12
TOL = _hypot_tol(ENTER_TOL, LEAVE_TOL) + FAN_DT


def apply_faults_arrow(table, cfg, context=None):
    ent = _col(table, "heating-coil-entering-air-temperature")
    leave = _col(table, "heating-coil-leaving-air-temperature")
    heat = _norm_cmd(table["heating-valve-command"])
    cool = _norm_cmd(table["cooling-valve-command"])
    damper = _norm_cmd(table["oa-damper-command"])
    rise = pc.greater(pc.subtract(leave, ent), TOL)
    m1 = pc.and_(pc.equal(heat, 0), pc.equal(cool, 0), pc.greater(damper, ECON_MIN))
    m2 = pc.and_(pc.equal(heat, 0), pc.greater(cool, 0), pc.greater(damper, 0.9))
    m3 = pc.and_(pc.equal(heat, 0), pc.greater(cool, 0), pc.less_equal(damper, ECON_MIN))
    return pc.and_(rise, pc.or_(m1, m2, m3))
```

---

## Starter pack (VAV / AHU baseline)

### `01_vav_zone_temp_bounds_occupied` (`VAV-C`)

```python
from open_fdd.arrow_runtime.cookbook import sensor_bounds_mask, _unoccupied_mask

FAULT_CODE = "VAV-C"


def apply_faults_arrow(table, cfg, context=None):
    occupied = pc.invert(_unoccupied_mask(table, cfg))
    oob = sensor_bounds_mask(table, "zone_temp", cfg)
    return pc.and_(oob, occupied)
```

### `02_vav_zone_temp_flatline_occupied` (`VAV-C`)

```python
from open_fdd.arrow_runtime.cookbook import sensor_flatline_mask, _unoccupied_mask

FAULT_CODE = "VAV-C"


def apply_faults_arrow(table, cfg, context=None):
    occupied = pc.invert(_unoccupied_mask(table, cfg))
    flat = sensor_flatline_mask(table, "zone_temp", cfg)
    return pc.and_(flat, occupied)
```

### `03_vav_damper_command_extreme_flatline` (`VAV-D`)

```python
from open_fdd.arrow_runtime.cookbook import flatline_1h_mask

FAULT_CODE = "VAV-D"
DAMPER = "damper-position-command"


def apply_faults_arrow(table, cfg, context=None):
    stuck = flatline_1h_mask(table, {**cfg, "column": DAMPER})
    wide = pc.greater(_norm_cmd(table[DAMPER]), 0.975)
    return pc.and_(stuck, wide)
```

### `04_ahu_runtime_outside_schedule` (`BLD-C`)

Use run-hours analytics script + schedule compare; boolean mask:

```python
from open_fdd.arrow_runtime.cookbook import _fan_on_mask, _unoccupied_mask

FAULT_CODE = "BLD-C"


def apply_faults_arrow(table, cfg, context=None):
    return pc.and_(_fan_on_mask(table, cfg), _unoccupied_mask(table, cfg))
```

### `05` / `06` / `07` — see Rules A, `sensor_bounds_mask` on `sa-t` / `sensor_flatline_mask` on `sa-t`

---

## Economizer starters

### `ahu_econ_100oa_temp_tracking_fault` (`AHU-E`)

```python
FAULT_CODE = "AHU-E"
DAMPER_FULL, FAN_ON, TRACK_TOL, FAN_HEAT = 0.95, 0.5, 2.0, 0.5


def apply_faults_arrow(table, cfg, context=None):
    oat, mat, sat = _col(table, "oa-t"), _col(table, "ma-t"), _col(table, "sa-t")
    damper = _norm_cmd(table["oa-damper-command"])
    fan = _col(table, "supply-fan-status")
    econ = pc.and_(pc.greater(fan, FAN_ON), pc.greater_equal(damper, DAMPER_FULL))
    mat_bad = pc.greater(pc.abs(pc.subtract(mat, oat)), TRACK_TOL)
    sat_bad = pc.greater(pc.abs(pc.subtract(pc.subtract(sat, FAN_HEAT), mat)), TRACK_TOL)
    return pc.and_(econ, pc.or_(mat_bad, sat_bad))
```

### `ahu_mech_cooling_when_free_cooling_available` (`AHU-E`)

```python
FAULT_CODE = "AHU-E"
MARGIN, DAMPER_LOW, COOL_ON = 2.0, 0.50, 0.10


def apply_faults_arrow(table, cfg, context=None):
    oat = _col(table, "oa-t")
    sp = _col(table, "sa-t-sp")
    damper = _norm_cmd(table["oa-damper-command"])
    cool = _norm_cmd(table["cooling-valve-command"])
    free = pc.less_equal(oat, pc.subtract(sp, MARGIN))
    return pc.and_(free, pc.less(damper, DAMPER_LOW), pc.greater_equal(cool, COOL_ON))
```

### `ahu_oa_damper_excess_open_extreme_ambient` (`AHU-E`)

```python
FAULT_CODE = "AHU-E"
DAMPER_MIN, HI_OAT, LO_OAT = 0.50, 70.0, 40.0


def apply_faults_arrow(table, cfg, context=None):
    oat = _col(table, "oa-t")
    damper = _norm_cmd(table["oa-damper-command"])
    extreme = pc.or_(pc.greater_equal(oat, HI_OAT), pc.less_equal(oat, LO_OAT))
    return pc.and_(pc.greater_equal(damper, DAMPER_MIN), extreme)
```

---

## VAV zones

### `zone_reheat_warm_ambient` (`VAV-A`)

```python
FAULT_CODE = "VAV-A"
T_CUTOFF, REHEAT_MIN = 78.0, 0.52


def apply_faults_arrow(table, cfg, context=None):
    oat = _col(table, "oa-t")
    reheat = _norm_cmd(table["reheat-valve-command"])
    return pc.and_(pc.greater(oat, T_CUTOFF), pc.greater(reheat, REHEAT_MIN))
```

### `zone_damper_valve_full_open` (`VAV-D`)

```python
FAULT_CODE = "VAV-D"
FULL_OPEN, ROLL = 97.5, 105


def apply_faults_arrow(table, cfg, context=None):
    d = _norm_cmd(table["damper-position-command"])
    hi = pc.greater(d, FULL_OPEN)
    rmin = arrow_rolling_min(d, ROLL)
    return pc.and_(hi, pc.greater(rmin, FULL_OPEN))
```

### Zone / IAQ bounds

Use `sensor_bounds_mask(table, "zone_temp", cfg)` or `sensor_bounds_mask` with CO₂ profile — see [sensor validation]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}#sensor-validation-bounds-flatline-rate-of-change).

---

## Central plant

### `dp_below_sp_pump_max` (`CH-E`)

```python
FAULT_CODE = "CH-E"
DP_MARGIN, PMP_HI, PMP_NEAR = 2.2, 0.93, 0.06


def apply_faults_arrow(table, cfg, context=None):
    dp = _col(table, "differential-pressure")
    sp = _col(table, "differential-pressure-sp")
    pump = _norm_cmd(table["pump-speed-command"])
    return pc.and_(
        pc.less(dp, pc.subtract(sp, DP_MARGIN)),
        pc.greater_equal(pump, PMP_HI - PMP_NEAR),
    )
```

### `flow_high_pump_max` (`CH-B`)

```python
FAULT_CODE = "CH-B"
FLOW_HI, PMP_HI, PMP_NEAR = 1100.0, 0.93, 0.06


def apply_faults_arrow(table, cfg, context=None):
    flow = _col(table, "water-flow")
    pump = _norm_cmd(table["pump-speed-command"])
    return pc.and_(pc.greater(flow, FLOW_HI), pc.greater_equal(pump, PMP_HI - PMP_NEAR))
```

### `plant_supply_temp_deadband` (`CH-D`)

```python
FAULT_CODE = "CH-D"
SP_BAND = 2.2


def apply_faults_arrow(table, cfg, context=None):
    temp = _col(table, "chilled-water-supply-temperature")
    sp = _col(table, "chilled-water-supply-temperature-sp")
    pump = _norm_cmd(table["pump-speed-command"])
    low = pc.less(temp, pc.subtract(sp, SP_BAND))
    high = pc.greater(temp, pc.add(sp, SP_BAND))
    return pc.and_(pc.greater(pump, 0.01), pc.or_(low, high))
```

### `chiller_excessive_runtime` (`CH-F`)

```python
from open_fdd.arrow_runtime.cookbook import arrow_rolling_mean

FAULT_CODE = "CH-F"
WINDOW, MAX_ON = 276, 264  # 5-min data ≈ 23 h window, 22 h max on


def apply_faults_arrow(table, cfg, context=None):
    on = pc.greater(_col(table, "chiller-status"), 0.5).cast(pa.float64())
    roll = arrow_rolling_mean(on, WINDOW)
    count = pc.multiply(roll, float(WINDOW))
    return pc.greater(count, float(MAX_ON))
```

---

## Heat pumps

### `hp_discharge_cold_when_heating` (`HP-D`)

```python
FAULT_CODE = "HP-D"
MIN_SAT, ZONE_COLD, FAN_ON = 85.0, 69.0, 0.01


def apply_faults_arrow(table, cfg, context=None):
    sat = _col(table, "sa-t")
    zone = _col(table, "stat_zn-t")
    fan = _col(table, "supply-fan-status")
    return pc.and_(
        pc.greater(fan, FAN_ON),
        pc.less(zone, ZONE_COLD),
        pc.less(sat, MIN_SAT),
    )
```

---

## Opportunistic / ventilation

### `econ_active_warm_ambient` (`AHU-E`)

```python
FAULT_CODE = "AHU-E"
T_CUTOFF, DPR_MIN = 63.0, 0.42


def apply_faults_arrow(table, cfg, context=None):
    oat = _col(table, "oa-t")
    damper = _norm_cmd(table["oa-damper-command"])
    return pc.and_(pc.greater(oat, T_CUTOFF), pc.greater(damper, DPR_MIN))
```

### `mech_cool_when_econ_available` (`AHU-E`)

```python
FAULT_CODE = "AHU-E"
T_CUTOFF, DPR_MAX = 63.0, 0.32


def apply_faults_arrow(table, cfg, context=None):
    oat = _col(table, "oa-t")
    damper = _norm_cmd(table["oa-damper-command"])
    cool = _norm_cmd(table["cooling-valve-command"])
    return pc.and_(pc.less(oat, T_CUTOFF), pc.less(damper, DPR_MAX), pc.greater(cool, 0.01))
```

### `low_oa_fraction_estimated` (`VAV-B`)

```python
FAULT_CODE = "VAV-B"
OA_MIN, GAP = 21.0, 2.2


def apply_faults_arrow(table, cfg, context=None):
    mat, rat, oat = _col(table, "ma-t"), _col(table, "ra-t"), _col(table, "oa-t")
    fan = _norm_cmd(table["supply-fan-speed-command"])
    denom = pc.subtract(oat, rat)
    safe = pc.greater(pc.abs(denom), GAP)
    num = pc.subtract(mat, rat)
    oa_pct = pc.multiply(pc.divide(num, denom), 100.0)
    low = pc.less(oa_pct, OA_MIN)
    return pc.and_(pc.greater(fan, 0.01), safe, low)
```

### `preheat_excess_temp` (`AHU-B`)

```python
FAULT_CODE = "AHU-B"
EXCESS = 2.2


def apply_faults_arrow(table, cfg, context=None):
    pre = _col(table, "preheat-coil-leaving-air-temperature")
    sp = _col(table, "sa-t-sp")
    oat = _col(table, "oa-t")
    valve = _norm_cmd(table["preheat-valve-command"])
    hot_oa = pc.and_(
        pc.greater(oat, sp),
        pc.greater(pc.subtract(pre, oat), EXCESS),
    )
    cold_oa = pc.and_(
        pc.less(oat, sp),
        pc.greater(pc.subtract(pre, sp), EXCESS),
    )
    return pc.and_(pc.greater(valve, 0.01), pc.or_(hot_oa, cold_oa))
```

---

## Weather station

### `weather_temp_spike` (`BLD-B`)

```python
from open_fdd.arrow_runtime.cookbook import rate_of_change_mask

FAULT_CODE = "BLD-B"


def apply_faults_arrow(table, cfg, context=None):
    return rate_of_change_mask(
        table,
        {**cfg, "max_per_sample": 16.0, "column": "oa-t"},
        col="oa-t",
    )
```

### `weather_gust_lt_wind` (`BLD-B`)

```python
FAULT_CODE = "BLD-B"


def apply_faults_arrow(table, cfg, context=None):
    gust = _col(table, "wind-gust-speed")
    wind = _col(table, "wind-speed")
    return pc.and_(
        pc.is_valid(gust),
        pc.is_valid(wind),
        pc.less(gust, wind),
    )
```

### RH bounds

```python
from open_fdd.arrow_runtime.cookbook import sensor_bounds_mask

FAULT_CODE = "DC-C"


def apply_faults_arrow(table, cfg, context=None):
    merged = {**cfg, "value_kind": "rh"}
    return sensor_bounds_mask(table, "relative_humidity", merged)
```

---

## Schedule + weather gating (occupied hours)

```python
from open_fdd.arrow_runtime.cookbook import _unoccupied_mask, _fan_on_mask

FAULT_CODE = "BLD-C"


def apply_faults_arrow(table, cfg, context=None):
    """Fan running when schedule says unoccupied."""
    return pc.and_(_fan_on_mask(table, cfg), _unoccupied_mask(table, cfg))
```

Pass `occupied_start_hour`, `occupied_end_hour`, `tz_offset_hours` in Rule Lab `cfg`.

---

## Next steps

1. Copy a module into `workspace/data/rules_py/<site>_<rule>.py`
2. Bind feather columns on the Rule Lab row
3. Set `fault_code` metadata
4. Quick-test on 3–24 h feather window
5. Ship via `setup_gl36_fdd.py` or Rule Lab save

**See also:** [Expression cookbook]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}) · [Fault codes]({{ "/fault-codes/" | relative_url }}) · [Rule Lab]({{ "/operator-bridge/rule-lab/" | relative_url }})
