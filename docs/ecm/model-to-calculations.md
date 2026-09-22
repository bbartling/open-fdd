---
title: Model → ECM calculations
parent: PyPI agent tools
nav_order: 6
permalink: /ecm/model-to-calculations.html
---

# Model → ECM calculations (ECM-ADAPT)

Typed adapter: **EQ-VOCAB quantity records + scenario** →
`open_fdd.ecm_engineering.calculate`. Python stays on **PyPI** — not on the
product HTTP path.

```python
from open_fdd.ecm_engineering import adapt_model_to_calculator

qty = {
    "schema_version": "ofdd_engineering_quantities_v1",
    "quantity_id": "q-elec-1",
    "property": "ratedElectricalInputPower",
    "numeric_value": 18.5,
    "unit_code": "kW",
    "quantity_kind": "ElectricalPower",
    "value_basis": "Rated",
    "source_type": "nameplate",
    "review_status": "Reviewed",
}
out = adapt_model_to_calculator(
    "fan_affinity",
    [qty],
    {
        "hours": 4000,
        "baseline_speed_fraction": 1.0,
        "proposed_speed_fraction": 0.8,
    },
)
assert out.ok
print(out.result["savings_kwh"])
```

## Supported methods (v1 adapter)

| Method | From model | From scenario (required) |
| --- | --- | --- |
| `fan_affinity` | `ratedElectricalInputPower` (kW, ElectricalPower) | hours, baseline/proposed speed fractions |
| `schedule_reduction` | `ratedElectricalInputPower` | baseline/proposed annual hours |
| `kw_per_ton_improvement` | (optional capacity context only) | annual_ton_hours + baseline/proposed kW/ton |

**Honesty:** capacity-only cooling records without `annual_ton_hours` return
`capacity_only` in `missing_evidence` — nameplate tons are not annual load.
Thermal kW cannot satisfy electrical `design_kw`.

Versioned context envelope (`ecm_context_v1`) remains complementary for agent
screening; this adapter is the calculator boundary.

See also: [Engineering quantities](../modeling/engineering-quantities.html),
[Agent context](agent-context.html).
