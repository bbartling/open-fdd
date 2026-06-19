---
title: GL36 & sensor patterns
parent: Rule Cookbook
nav_order: 5
redirect_from:
  - /expression_rule_cookbook
  - /expression_rule_cookbook.html
---

# GL36 & sensor patterns

Fault-code mapping and sensor-validation patterns for **PyArrow** rules. For backend choice and a side-by-side tutorial, see [PyArrow & DataFusion SQL]({{ "/rule-cookbook/dual-backend-rules/" | relative_url }}).

Executable modules live in `workspace/data/rules_py/`. Copy-paste sources: [Python recipes (Arrow)]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}).

---

## Rule structure

1. **Historian columns** — Feather names from BACnet poll (`oa-t`, `sa-t`, `stat_zn-t`, …) or BRICK labels via model export.
2. **Module constants** — Thresholds at top of file or read from `cfg` for site tuning.
3. **`apply_faults_arrow`** — Returns a **boolean PyArrow array** (True = fault sample).
4. **`fault_code`** — Set in Rule Lab; must exist in `GET /api/faults/catalog`.

```python
import pyarrow.compute as pc
from open_fdd.arrow_runtime.cookbook import sensor_bounds_mask

def apply_faults_arrow(table, cfg, context=None):
    return sensor_bounds_mask(table, "zone_temp", cfg)
```

### Command scaling (0–1 vs 0–100 %)

```python
def _norm_cmd(col):
    return pc.if_else(pc.greater(col, 1.0), pc.divide(col, 100.0), col)
```

### Occupied hours (schedule gating)

Use `open_fdd.arrow_runtime.cookbook._unoccupied_mask` or compare local hour from `timestamp`. Fan on when unoccupied → **BLD-C**.

---

## Sensor validation (bounds, flatline, rate of change)

Use **`open_fdd.arrow_runtime.sensor_catalog.SENSOR_PROFILES`** for defaults, or tune per site in Rule Lab `cfg`.

### Bounds (out of range)

| Sensor kind | Min | Max | Flatline tol | Max Δ / hour | Max Δ / 15 min | Fault code |
|-------------|-----|-----|--------------|--------------|----------------|------------|
| Zone temp (°F) | 55 | 90 | 0.10 | 4.0 | 2.0 | **VAV-C** |
| Supply air temp | 50 | 110 | 0.15 | 8.0 | 3.0 | **AHU-C**, **RTU-C** |
| Return air temp | 55 | 95 | 0.10 | 3.0 | 1.5 | **AHU-D** |
| Mixed air temp | 40 | 110 | 0.15 | 6.0 | 2.5 | **AHU-D** |
| Outdoor air temp | −40 | 130 | 0.10 | 12.0 | 6.0 | **BLD-B** |
| Duct static (inH₂O) | −0.5 | 3.0 | 0.02 | 0.5 | 0.25 | **AHU-A** |
| Relative humidity (%) | 0 | 100 | 1.0 | 15.0 | 8.0 | **DC-C** |
| Chilled water (°F) | 40 | 90 | 0.10 | 4.0 | 2.0 | **CH-D** |
| Hot water (°F) | 70 | 200 | 0.15 | 6.0 | 3.0 | **CH-D** |
| Condenser water (°F) | 50 | 110 | 0.15 | 5.0 | 2.5 | **CH-A** |
| CO₂ (ppm, occupied) | 400 | 1000 | 5.0 | 200 | 80 | **VAV-B** |
| Discharge air temp | 45 | 120 | 0.15 | 10.0 | 4.0 | **VAV-E**, **HP-D** |

When OAT/RAT/MAT are all present, prefer **mixing envelope** over RAT bounds alone.

### Flatline (stuck sensor)

Default **12 samples ≈ 1 hour** at 5-minute poll.

```python
from open_fdd.arrow_runtime.cookbook import sensor_flatline_mask

def apply_faults_arrow(table, cfg, context=None):
    return sensor_flatline_mask(table, "outdoor_air_temp", cfg)  # BLD-B
```

### Rate of change (spike)

```python
from open_fdd.arrow_runtime.cookbook import rate_of_change_mask
from open_fdd.arrow_runtime.sensor_catalog import cfg_from_profile

def apply_faults_arrow(table, cfg, context=None):
    merged = cfg_from_profile("outdoor_air_temp", cfg)
    merged["samples_per_hour"] = 12
    return rate_of_change_mask(table, merged, col="oa-t")
```

### Mixing envelope (MAT vs OAT/RAT)

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

## GL36-inspired AHU rules

ASHRAE Guideline 36-style patterns. Assign **`fault_code`** in Rule Lab.

| Rule | Summary | Code | Module |
|------|---------|------|--------|
| A — duct static low @ full fan | SP below setpoint at high VFD | **AHU-A** | [Rule A]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-a--duct-static-low-at-full-fan-speed-ahu-a) |
| B — blend below band | MAT below OAT/RAT envelope | **AHU-D** | [Rules B & C]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rules-b--c--blended-air-outside-oatr-at-band-ahu-d) |
| C — blend above band | MAT above OAT/RAT envelope | **AHU-D** | [Rules B & C]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rules-b--c--blended-air-outside-oatr-at-band-ahu-d) |
| D — discharge cold when heating | SAT low vs MAT, heat valve open | **AHU-B** | [Rule D]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-d--discharge-cold-when-heating-commanded-ahu-b) |
| E — SAT low, full heating | SAT below SP, valve > 90% | **AHU-C** | [Rule E]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-e--sat-too-low-with-full-heating-ahu-c) |
| F — SAT/MAT mismatch econ | Econ mode, SAT ≠ MAT | **AHU-E** | [Rule F]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-f--satmat-mismatch-in-economizer-mode-ahu-e) |
| G — ambient warm free cool | OAT > SAT SP, econ open, cool off | **AHU-E** | [Rule G]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-g--ambient-too-warm-for-free-cooling-ahu-e) |
| H — OAT/MAT mismatch econ+mech | Mech + econ, MAT ≠ OAT | **AHU-E** | [Rule H]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-h--oatmat-mismatch-econ--mech-cooling-ahu-e) |
| I — OAT/MAT mismatch econ-only | Econ only, MAT ≠ OAT | **AHU-E** | [Rule I]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-i--oatmat-mismatch-economizer-only-ahu-e) |
| J — discharge above blend cooling | SAT > MAT in cooling | **AHU-B** | [Rule J]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-j--discharge-above-blended-in-cooling-ahu-b) |
| K — discharge above SP full cool | SAT > SP, full cooling | **AHU-C** | [Rule K]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-k--discharge-above-setpoint-in-full-cooling-ahu-c) |
| L — cooling coil ΔT when off | CHW drop when valves closed | **CH-C** | [Rule L]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-l--cooling-coil-δt-when-inactive-ch-c) |
| M — heating coil ΔT when off | HW rise when valves closed | **AHU-B** | [Rule M]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-m--heating-coil-δt-when-inactive-ahu-b) |
| FC4 — PID hunting | Excessive command reversals | **AHU-G** / **VAV-F** / **CH-G** / **RTU-E** | [FC4]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#fc4--pid-hunting-legacy-gl36) |

---

## Baseline deploy bundle

| Pattern | Arrow approach | Fault code |
|---------|----------------|------------|
| Zone temp bounds (occupied) | `sensor_bounds_mask` + occupied mask | **VAV-C** |
| Zone temp flatline (occupied) | `sensor_flatline_mask` + occupied | **VAV-C** |
| Damper command flatline | `flatline_1h_mask` on damper cmd | **VAV-D** |
| Runtime outside schedule | `after_hours_fan_satisfied_mask` | **BLD-C** |
| Duct static not maintained | [Rule A]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#rule-a--duct-static-low-at-full-fan-speed-ahu-a) | **AHU-A** |
| Internal temp bounds / flatline | `sensor_bounds_mask` / `sensor_flatline_mask` on SAT | **AHU-C** |

Economizer starters: [economizer section]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#economizer-starters).

VAV, plant, heat pump: [VAV]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#vav-zones) · [Central plant]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#central-plant) · [Heat pumps]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}#heat-pumps).

---

## Data quality vs equipment faults

| Symptom | Pattern | Code |
|---------|---------|------|
| Flatline 1 h | `flatline_1h` | **VAV-C**, **AHU-C**, **BLD-B** |
| OOB sample | `oob_rolling` | sensor-specific |
| Spike between polls | `rate_of_change` | **BLD-B** |
| No new samples | `stale_points` | **BLD-D** |
| MAT ∉ [OAT, RAT] | `mixing_envelope` | **AHU-D** |

Gate sensor faults with **fan on**, **valve open**, or **occupied** where appropriate — [Sensor & data quality]({{ "/fault-codes/sensor-quality/" | relative_url }}).

---

## Metric (°C) equivalents

Set `cfg["temp_unit"] = "metric"` or scale constants: 55 °F ≈ 12.8 °C, 90 °F ≈ 32.2 °C, 2.0 °F tol ≈ 1.1 °C.

---

## Binding to the fault catalog

1. Pick a **letter code** from [Fault codes]({{ "/fault-codes/" | relative_url }}).
2. Set **fault_code** in Rule Lab.
3. Batch FDD aggregates into `GET /api/faults/status`.

**Next:** [Python recipes (Arrow)]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}) · [Rule Lab]({{ "/operator-bridge/rule-lab/" | relative_url }})
