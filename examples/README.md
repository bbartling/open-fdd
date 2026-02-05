# Examples

Scripts and sample data for **open-fdd** tutorials.

## Contents

| File | Description |
|------|-------------|
| `check_faults_ahu7_flatline.py` | Flatline (stuck sensor) detection |
| `check_faults_ahu7_bounds.py` | Bounds (out-of-range) sensor check |
| `my_rules/sensor_flatline.yaml` | Flatline rule config (your rules) |
| `my_rules/sensor_bounds.yaml` | Bounds rule config (your rules) |
| `brick_model.ttl` | Brick TTL model (optional) |
| `brick_resolver.py` | Resolve column map from TTL |

## Data

The tutorials use `data_ahu7.csv` (~10k rows, AHU7 BAS export). Place it in this directory before running the scripts.

## Run

```bash
cd examples
python check_faults_ahu7_flatline.py
python check_faults_ahu7_bounds.py
```
