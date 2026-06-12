---
title: Central plants (CHW / CTW / BLR)
parent: Rule Cookbook
nav_order: 20
---

# Central plant Arrow recipes

Chiller plant, condenser water, cooling tower, boiler, and hot-water distribution faults use the same Arrow-native primitives as air-side rules.

## Starter fault codes

| Code | Primitive | Recipe |
|------|-----------|--------|
| `CHW-DT-001` | `low_delta_t_mask` | Low chilled-water ΔT syndrome |
| `CHW-DP-001` | `reset_stuck_mask` | CHW differential pressure reset stuck high |

## Required point roles (CHW)

- `chw_supply_temp`, `chw_return_temp` — ΔT rules
- `chw_dp`, `chw_dp_setpoint` — reset stuck rules
- `pump_command`, `pump_feedback` — command/feedback mismatch

## Synthetic test pattern

```python
import pyarrow as pa
from open_fdd.arrow_runtime.primitives import low_delta_t_mask

table = pa.table({
    "chw_supply_temp": [44.0] * 10,
    "chw_return_temp": [44.5] * 10,
})
mask = low_delta_t_mask(
    table,
    {"min_delta_t": 4.0},
    supply_col="chw_supply_temp",
    return_col="chw_return_temp",
)
assert mask.to_pylist()[-1] is True
```

See [Fault codes — chiller plant]({{ "/fault-codes/" | relative_url }}) (expanded in 3.0.19).
