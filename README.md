# open-fdd

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version)

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

**Config-driven FDD** for HVAC — YAML rules, pandas DataFrames, optional Brick model. 

Pandas is an excellent choice for high-performance, tabular-style computing, especially for rule- or expression-based fault detection equations, and it has become a standard tool across modern data science, machine learning, and AI workflows. **Pandas** is an open-source Python library that provides fast, spreadsheet-like data tables called DataFrames, making it easy to clean, analyze, and compute with time-series and tabular data using simple, Excel-style operations at much larger scales; it was created in 2008 by Wes McKinney while working in finance to handle large time-series datasets more efficiently and later became a core project in the scientific Python ecosystem under the NumFOCUS foundation.


> open fdd is under construction with daily updates please stay tuned for a new version 2.0!


## Quick Start

Map BRICK class names to your DataFrame columns, then run rules:

```python
import pandas as pd
from pathlib import Path
from open_fdd import RuleRunner
from open_fdd.engine import load_rule
from open_fdd.reports import summarize_fault, print_summary

df = pd.DataFrame({
    "timestamp": [
        "2023-01-01 00:00", "2023-01-01 00:15", "2023-01-01 00:30", "2023-01-01 00:45",
    ],
    "duct_static": [0.4, 0.4, 0.2, 0.2],
    "duct_static_setpoint": [0.5, 0.5, 0.5, 0.5],
    "supply_vfd_speed": [0.95, 0.95, 0.95, 0.95],
})

# BRICK class -> your DataFrame column
column_map = {
    "Supply_Air_Static_Pressure_Sensor": "duct_static",
    "Supply_Air_Static_Pressure_Setpoint": "duct_static_setpoint",
    "Supply_Fan_Speed_Command": "supply_vfd_speed",
}

rules_dir = Path("open_fdd/rules")
runner = RuleRunner(rules=[load_rule(rules_dir / "ahu_fc1.yaml")])
result = runner.run(
    df,
    timestamp_col="timestamp",
    column_map=column_map,
    rolling_window=3,  # fault only if true for 3+ consecutive samples
)
summary = summarize_fault(
    result,
    "fc1_flag",
    timestamp_col="timestamp",
    motor_col=column_map["Supply_Fan_Speed_Command"],
)
print_summary(summary, "FC1 Low Duct Static")
```

## Rule expression example (FC9)

Rules use BRICK class names in `inputs`; `column_map` maps them to your DataFrame:

```yaml
name: oat_too_high_free_cooling
type: expression
flag: fc9_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  oat:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  sat_setpoint:
    brick: Supply_Air_Temperature_Setpoint
    column: sat_setpoint
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig
  cooling_sig:
    brick: Valve_Command
    column: cooling_sig

params:
  outdoor_err_thres: 1.0
  delta_t_supply_fan: 0.5
  supply_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  (oat - outdoor_err_thres > sat_setpoint - delta_t_supply_fan + supply_err_thres) & (economizer_sig > ahu_min_oa_dpr) & (cooling_sig < 0.1)
```

With Brick TTL, use `resolve_from_ttl("model.ttl")` instead of a manual `column_map`.

## Getting Started

Please see the online docs for setup and running HVAC fault checks with pandas.

[📖 Docs](https://bbartling.github.io/open-fdd/)


## Contributing

Open FDD is under construction but will be looking for testers and contributors soon, especially to complete a future open-source fault rule cookbook.

## License

MIT
