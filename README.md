# open-fdd

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Black](https://img.shields.io/badge/code%20style-black-000000.svg)

![snip](https://raw.githubusercontent.com/bbartling/open-fdd/config-driven-v2/snip.png)


**open-fdd** is a **config-driven Fault Detection and Diagnostics (FDD)** library for HVAC systems. Define fault rules in YAML, run them against pandas DataFrames. Inspired by ASHRAE/NIST guidelines and SkySpark/Axon-style logic.

## Features

- **Config-driven rules** — YAML-based fault definitions (bounds, flatline, expression, hunting, OA fraction, ERV)
- **Pandas-native** — Works directly with DataFrames
- **AHU rules** — FC1–FC16 (duct static, mix temp, PID hunting, economizer, coils, ERV)
- **Chiller plant** — Pump differential pressure, CHW flow
- **Sensor checks** — Bounds (imperial/metric) and flatline detection
- **Fault analytics** — Duration, motor runtime, sensor stats when faulted

## Installation

```bash
pip install open-fdd
```

Or from source:

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
pip install -e ".[dev]"
```

## Quick Start

```python
import pandas as pd
from open_fdd import RuleRunner
from open_fdd.air_handling_unit.reports import summarize_fault, print_summary

# Sample AHU data
df = pd.DataFrame({
    "timestamp": pd.date_range(start="2023-01-01", periods=100, freq="15min"),
    "duct_static": [0.4] * 50 + [0.2] * 50,
    "duct_static_setpoint": [0.5] * 100,
    "supply_vfd_speed": [0.95] * 100,
    "mat": [60] * 100,
    "rat": [72] * 100,
    "oat": [50] * 100,
})

# Run rules
runner = RuleRunner("open_fdd/rules")
df_result = runner.run(df, rolling_window=3)

# Analytics
summary = summarize_fault(df_result, "fc1_flag", motor_col="supply_vfd_speed")
print_summary(summary, "FC1 Low Duct Static")
```

## Rule Types

| Type | Description |
|------|-------------|
| `bounds` | Value outside [low, high]; supports `units: metric` |
| `flatline` | Sensor stuck (rolling spread < tolerance) |
| `expression` | Pandas/numpy expression |
| `hunting` | Excessive AHU state changes (PID hunting) |
| `oa_fraction` | OA fraction / design airflow error |
| `erv_efficiency` | ERV effectiveness out of range |

## Rule Structure

```yaml
name: my_rule
type: expression
flag: my_flag

inputs:
  col_a:
    column: actual_df_column_name
  col_b:
    column: other_column

params:
  thres: 0.1

expression: |
  (col_a < col_b - thres) & (col_a > 0)
```

## Creating custom rules

You can define your own rules in YAML. The `expression` type is the most flexible — use any pandas/numpy expression against your columns:

```yaml
name: my_custom_rule
type: expression
flag: my_fault_flag

inputs:
  temp_a:
    column: sensor_1   # maps to your DataFrame column
  temp_b:
    column: sensor_2

params:
  threshold: 5.0

expression: |
  (temp_a - temp_b) > threshold
```

Put your rules in a directory and load them:

```python
runner = RuleRunner("path/to/your/rules")
df_result = runner.run(df)
```

Or pass rule dicts directly: `RuleRunner(rules=[{...}])`. Use `skip_missing_columns=True` when your DataFrame doesn't have all columns for every rule.

## Metric Units

For sensor bounds, pass `params={"units": "metric"}`:

```python
runner.run(df, params={"units": "metric"})
```

## Project Layout

```
open_fdd/
├── engine/          # RuleRunner, checks
├── rules/           # YAML rule configs (AHU, chiller, sensor)
├── air_handling_unit/
│   └── reports/     # Fault analytics (summarize_fault, etc.)
└── tests/
```

## Contributing

1. Clone and install: `pip install -e ".[dev]"`
2. Run tests: `pytest open_fdd/tests/`
3. Format: `black open_fdd/`
4. Submit a PR

## License

MIT — see [LICENSE](LICENSE).
