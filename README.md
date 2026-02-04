# open-fdd

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version)

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)

**Config-driven FDD** for HVAC — YAML rules, pandas DataFrames, optional Brick model. 

Pandas is an excellent choice for high-performance, tabular-style computing, especially for rule- or expression-based fault detection equations, and it has become a standard tool across modern data science, machine learning, and AI workflows. **Pandas** is an open-source Python library that provides fast, spreadsheet-like data tables called DataFrames, making it easy to clean, analyze, and compute with time-series and tabular data using simple, Excel-style operations at much larger scales; it was created in 2008 by Wes McKinney while working in finance to handle large time-series datasets more efficiently and later became a core project in the scientific Python ecosystem under the NumFOCUS foundation.


[📖 Docs](https://bbartling.github.io/open-fdd/)

> open fdd is under construction with daily updates please stay tuned for a new version 2.0!


## Quick Start

```python
import pandas as pd
from open_fdd import RuleRunner
from open_fdd.reports import summarize_fault, print_summary

df = pd.DataFrame({
    "timestamp": [
        "2023-01-01 00:00", "2023-01-01 00:15", "2023-01-01 00:30", "2023-01-01 00:45"
    ],

    "duct_static": [0.4, 0.4, 0.2, 0.2, 0.2],
    "duct_static_setpoint": [0.5, 0.5, 0.5, 0.5, 0.5],
    "supply_vfd_speed": [0.95, 0.95, 0.95, 0.95, 0.95],
    "mat": [60.3, 60.2, 60.3, 60.3, 60.4],
    "rat": [72.0, 72.1, 72.0, 72.0, 72.1],
    "oat": [53.3, 53.3, 53.3, 53.4, 53.4],
})

runner = RuleRunner("open_fdd/rules")
df_result = runner.run(df, rolling_window=3)  # fault only if true for 3+ consecutive samples
summary = summarize_fault(df_result, "fc1_flag", motor_col="supply_vfd_speed")
print_summary(summary, "FC1 Low Duct Static")
```

## Rule expression example (FC9)

Rules are YAML with `inputs`, `params`, and an `expression`. BRICK metadata links rule inputs to Brick classes:

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
  ahu_min_oa_dpr: 0.1

expression: |
  (oat - outdoor_err_thres > sat_setpoint - delta_t_supply_fan + supply_err_thres) & (economizer_sig > ahu_min_oa_dpr) & (cooling_sig < 0.1)
```

## Install

```bash
pip install open-fdd
```

From source (contributing):

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
pip install -e ".[dev]"
pytest open_fdd/tests/
```

## BRICK model driven

Column mapping uses BRICK class names. Resolve from a Brick TTL:

```bash
pip install open-fdd[brick]
python examples/check_faults_ahu7.py
```

```python
from open_fdd import RuleRunner, resolve_from_ttl

column_map = resolve_from_ttl("path/to/brick_model.ttl")  # BRICK class -> CSV column
runner = RuleRunner("open_fdd/rules")
result = runner.run(df, column_map=column_map)
```

## Contributing

1. `git clone` and `pip install -e ".[dev]"`
2. `pytest open_fdd/tests/`
3. `black open_fdd/`
4. PR

## License

MIT
