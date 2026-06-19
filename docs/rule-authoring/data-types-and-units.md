---
title: Data types and units
parent: Rule authoring (v1)
nav_order: 3
---

# Data types and units

Rules read **columnar historian tables** produced by BACnet / Niagara / JSON API ingest. Author against **Feather column names** (`oa-t`, `stat_zn-t`, …) or BRICK `fdd_input` aliases resolved in the bridge.

## Required table shape

| Column / convention | Expectation |
|---------------------|-------------|
| `timestamp` | UTC or site-local consistent ordering; monotonic within a batch window |
| Point columns | One float (or castable) column per bound historian point |
| `site_id` | Optional in table; often passed via `cfg` / `context` |
| Row count | One row per poll sample — irregular spacing is normal |

Missing columns: cookbook helpers typically return an all-`False` mask or zero-filled stand-ins — check helper docs before assuming a fault.

## Numeric casting and nulls

| Older off-repo gist | Arrow in Open-FDD |
|----------------------|--------------|
| `HelperUtils.convert_to_float` | `pc.cast(col, pa.float64())` or ingest-time typing |
| `HelperUtils.check_datatype_float` | Rule Lab lint + bridge ingest validation |
| `HelperUtils.check_datatype_int` | Validate integer **cfg** fields (`int(cfg["window_samples"])`) |
| `np.maximum` / `np.minimum` | `pc.max` / `pc.min` |
| `series.rolling(n).min()` | `arrow_rolling_min` in `open_fdd.arrow_runtime.windows` |
| `series.diff()` | `arrow_diff` / `arrow_abs_diff` |
| `df.resample("H")` | **Not ported 1:1** — use sample-window rolling helpers instead |

**Null behavior:** comparisons involving null produce null; backend cast may treat null as false in the final mask. Prefer `pc.fill_null` or explicit guards when null should mean “no fault.”

## Command normalization

BACnet analog outputs often arrive as **0–100 %**. Open-FDD normalizes with `norm_cmd_array()`:

- Values **> 1.0** → divide by 100 (0–1 fraction)
- Values **≤ 1.0** → used as-is (already fractional)

Legacy gist: `check_range_less_than_one` / `float_max_check_err` (command max ≤ 1.0 after conversion).

Configure per rule:

```python
cfg = {"min_active_command": 0.02, "min_command_delta": 0.03}
```

## Boolean / status columns

| Signal | Typical handling |
|--------|------------------|
| Fan status / run command | Normalize as command; gate with `pc.greater(fan, 0.01)` |
| Occupancy | Boolean column or hour-of-week mask via cookbook schedule helpers |
| Enable / alarm state | Cast to bool; combine with `pc.and_` |
| Binary points | `pc.equal(col, 1)` or cast from 0/1 floats |

## Sensor profiles and units

Default bounds, flatline tolerance, and rate limits live in `open_fdd.arrow_runtime.sensor_catalog.SENSOR_PROFILES`.

| Profile key | Quantity | Default unit | Example fault codes |
|-------------|----------|--------------|---------------------|
| `zone_temp` | Temperature | °F | VAV-C |
| `supply_air_temp` | Temperature | °F | AHU-C, RTU-C |
| `outdoor_air_temp` | Temperature | °F | BLD-B |
| `mixed_air_temp` | Temperature | °F | AHU-D |
| `return_air_temp` | Temperature | °F | AHU-D |
| `duct_static_pressure` | Pressure | in H₂O | AHU-A |
| `zone_humidity` | Relative humidity | % RH | BLD-B |
| `co2` | CO₂ | ppm | BLD-B |

Override via rule `cfg` (`bounds_low`, `bounds_high`, `flatline_tolerance`, `window_samples`, `max_per_hour`). Metric sites: set `cfg["temp_unit"] = "metric"` or scale constants (see [Expression cookbook]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}#metric-c-equivalents)).

## Time and windows

| Setting | Meaning |
|---------|---------|
| `window_samples` | Rolling window in **poll samples** (not wall-clock unless derived) |
| `rolling_avg_minutes` | Converted to samples using `poll_interval_s` / median poll interval |
| `hunting_window_hours` | Used by PID hunting helpers to derive sample count |
| `min_true_rows` | Confirmation: consecutive true samples required |
| `min_elapsed_minutes` | Confirmation: minimum wall time with fault true |

Irregular timestamps: rolling helpers operate on row order within the loaded table — ensure lookback windows include enough samples for your poll cadence.

## Raw fault vs confirmed fault

| Stage | Where |
|-------|-------|
| Raw mask | Return value of `apply_faults_arrow` |
| Confirmed mask | `ArrowRuleResult.fault_mask` after `apply_fault_confirmation_from_cfg` |

Document both when tuning — a rule may fire briefly but not meet confirmation.

## Related

- [GL36 & sensor patterns — sensor validation]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}#sensor-validation-bounds-flatline-rate-of-change)
- [Fault confirmation]({{ "/rule-cookbook/fault-confirmation/" | relative_url }})
- [PyArrow & DataFusion SQL]({{ "/rule-cookbook/dual-backend-rules/" | relative_url }})
