# AHU7 Example

Beginner notebook example using real AHU7 data with synthetic fault windows for learning.

## What you get

- `run_and_viz_faults.ipynb` — simple tutorial notebook
- `../data/AHU7.csv` — real AHU7 dataset

## Run

```bash
cd /path/to/open-fdd
./.venv/bin/python -m jupyter lab
# open examples/AHU7/run_and_viz_faults.ipynb
```

## What it teaches

- load/parse time-series data
- create easy bounds + flatline fault flags
- plot sensor trends and flags
- compute monthly fault-rate summaries
