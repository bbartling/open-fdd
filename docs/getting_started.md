---
title: Getting Started
nav_order: 2
---

# Getting Started — AHU7 Tutorial

Jump right in. Run sensor checks (bounds + flatline) on AHU7 data.

## 1. Install

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
pip install -e ".[dev]"
```

## 2. Run the AHU7 script

The `open-fdd` repository includes an [examples directory](https://github.com/bbartling/open-fdd/tree/master/examples) with various scripts. Specifically for this tutorial, we will be using the `ahu7_standalone.py` script.

This image shows an example of an Air Handling Unit (AHU):
![AHU in the GitHub Pages](https://raw.githubusercontent.com/bbartling/open-fdd/master/examples/rtu7_snip.png)

To run the example, navigate to the root directory of the `open-fdd` repository, create and activate a virtual environment, and then execute the script.

```bash
# From the root directory of the open-fdd repository
python3 -m venv venv
source venv/bin/activate
python examples/ahu7_standalone.py
```

The `examples/ahu7_sample.csv` file (500 rows) is included in the repository. The `ahu7_standalone.py` script runs bounds and flatline checks on this data and prints the fault counts. Try it yourself.

## 3. What the script does

```python
import pandas as pd
from pathlib import Path

import open_fdd
from open_fdd import RuleRunner

script_dir = Path(__file__).parent
csv_path = script_dir / "ahu7_sample.csv"
df = pd.read_csv(csv_path)
df["timestamp"] = pd.to_datetime(df["timestamp"])

# Manual column mapping: BMS column names → rule input names
column_map = {
    "sat": "SAT (°F)",
    "mat": "MAT (°F)",
    "oat": "OAT (°F)",
    "rat": "RAT (°F)",
}

rules_dir = Path(open_fdd.__file__).parent / "rules"
runner = RuleRunner(rules_path=rules_dir)
runner._rules = [
    r for r in runner._rules
    if r.get("name") in ("bad_sensor_check", "sensor_flatline")
]

result = runner.run(
    df,
    timestamp_col="timestamp",
    params={"units": "imperial"},
    skip_missing_columns=True,
    column_map=column_map,
)
print("Bounds:", result["bad_sensor_flag"].sum())
print("Flatline:", result["flatline_flag"].sum())
```

`column_map` tells the runner which DataFrame columns map to rule inputs (`oat`, `sat`, etc.). `rolling_window` (not used here) would require a fault to hold for N consecutive samples before flagging.

## 4. Slightly harder: BRICK data model

Use a Brick TTL to resolve columns instead of a hardcoded dict:

```bash
pip install open-fdd[brick]
python examples/ahu7_standalone.py
```

With `open-fdd[brick]`, the script loads `examples/ahu7_brick_model.ttl` and uses `brick_resolver.resolve_from_ttl()` to build `column_map` from `ofdd:mapsToRuleInput` + `rdfs:label`. No manual mapping.

See **[Data Model & Brick](data_model.md)** for the full picture.
