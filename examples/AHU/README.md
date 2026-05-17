# AHU workshop CSVs and rules

This folder holds sample trend exports (`AHU7.csv`, `RTU11.csv`) and YAML rule packs: the full workshop set under `rules/`, and **`rules_rtu11_temp_only/`** (sensor bounds + flatline on **AHU supply / mixed / outside / return air temperatures** only).

## Run rules with RuleRunner

From the repository root with **`open-fdd[engine]`** installed:

```python
from pathlib import Path
import pandas as pd
from open_fdd.engine import RuleRunner

csv_path = Path("examples/AHU/RTU11.csv")
rules_path = Path("examples/AHU/rules_rtu11_temp_only")

df = pd.read_csv(csv_path, parse_dates=["timestamp"])
runner = RuleRunner(rules_path=rules_path)
out = runner.run(
    df,
    timestamp_col="timestamp",
    column_map={
        "Supply_Air_Temperature_Sensor": "supply_air_temp",
        # ... match keys to your rule inputs
    },
)
print([c for c in out.columns if c.endswith("_flag")])
```

See [Expression rule cookbook](https://github.com/bbartling/open-fdd/blob/master/docs/expression_rule_cookbook.md) for expression patterns and column-map conventions.

## Site profiles (optional)

`site_profiles.yaml` and `site_profiles_rtu11_temp.yaml` describe CSV paths, equipment labels, and BRICK-style mapping metadata for workshops. Use them as reference when building your own **`column_map`** or manifest YAML.

## Notebooks

`RTU7_standardized_refactored.ipynb` and `RTU11_standardized_refactored.ipynb` walk through exploratory plots and rule runs on the sample CSVs.
