# ML Regression PoC Example

Minimal proof-of-concept showing how ML can be combined with YAML-style rule settings.

## What you get

- `ml_regression_fault_poc.ipynb` — beginner ML + fault-flag notebook
- uses `../data/AHU7.csv` as source data

## Run

```bash
cd /path/to/open-fdd
./.venv/bin/python -m jupyter lab
# open examples/ML/ml_regression_fault_poc.ipynb
```

## What it teaches

- define model + threshold config in YAML text
- fit simple linear regression (`fan_speed_pct` vs `duct_pressure`)
- compute residuals
- create `ml_residual_fault_flag` from residual threshold
- visualize and summarize monthly fault rates
