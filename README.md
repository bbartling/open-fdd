# open-fdd

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Black](https://img.shields.io/badge/code%20style-black-000000.svg)

![open-fdd logo](https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png)


> open fdd is under construction at the moment stay tuned!

Please see [Pypi](https://pypi.org/project/open-fdd/) for the legacy open-fdd until the version 2 is ready. Also coming the future will be [open-fdd-core](https://github.com/bbartling/open-fdd-core) for a full blown framework to boostrap TimescaleDB, Brick TTL, and web API to ingest CSV → run faults via `POST /faults/run` or the Python API. Rules resolve from the Brick model (`fdd_input`); no column mapping needed at runtime.


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

# Sample AHU data set in Pandas computing library format
df = pd.DataFrame({
    "timestamp": [
        "2023-01-01 00:00", "2023-01-01 00:15", "2023-01-01 00:30",
        "2023-01-01 00:45", "2023-01-01 01:00", "2023-01-01 01:15",
        "2023-01-01 01:30", "2023-01-01 01:45", "2023-01-01 02:00",
        "2023-01-01 02:15"
    ],

    "duct_static": [0.4, 0.4, 0.4, 0.4, 0.4, 0.2, 0.2, 0.2, 0.2, 0.2],
    "duct_static_setpoint": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
    "supply_vfd_speed": [0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95],
    "mat": [60, 60, 60, 60, 60, 60, 60, 60, 60, 60],
    "rat": [72, 72, 72, 72, 72, 72, 72, 72, 72, 72],
    "oat": [50, 50, 50, 50, 50, 50, 50, 50, 50, 50],
})

# Run rules
runner = RuleRunner("open_fdd/rules")
df_result = runner.run(df, rolling_window=3)

# Analytics
summary = summarize_fault(df_result, "fc1_flag", motor_col="supply_vfd_speed")
print_summary(summary, "FC1 Low Duct Static")
```

## AHU7 sensor checks (standalone)

Run bounds + flatline on the packaged sample without open-fdd-core:

```bash
python examples/ahu7_standalone.py
```

Uses `examples/ahu7_sample.csv` (500 rows). For full dataset, place `ahu7_data.csv` in `examples/`. See [docs/examples.md](docs/examples.md). Imperial units (°F); pass `params={"units": "metric"}` only if your data is already in °C.

## Rule Types

| Type | Description |
|------|-------------|
| `bounds` | Value outside [low, high]; supports `units: metric`. See `open_fdd/rules/sensor_bounds.yaml` |
| `flatline` | Sensor stuck (rolling spread < tolerance over window). See `open_fdd/rules/sensor_flatline.yaml` |
| `expression` | Pandas/numpy expression |
| `hunting` | Excessive AHU state changes (PID hunting) |
| `oa_fraction` | OA fraction / design airflow error |
| `erv_efficiency` | ERV effectiveness out of range |

## Rule Structure

**Expression** (flexible; any pandas/numpy expression):

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

**Bounds** (bad data): `inputs.*.bounds` = `[low, high]` or `{imperial: [...], metric: [...]}`.

**Flatline** (stuck sensor): `inputs.*.column` + `params.tolerance` and `params.window`.

Full YAML for both: [docs/examples.md](docs/examples.md)

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
