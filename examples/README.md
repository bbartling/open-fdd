# Examples

- **ahu7_sample.csv** — 500-row AHU7 sample (~80KB), included in repo.
- **ahu7_standalone.py** — Run sensor checks (bounds + flatline) without open-fdd-core. Uses imperial units (°F).

**Run:**
```bash
python examples/ahu7_standalone.py
```

For the full dataset (~10k rows, 1.6MB), place `ahu7_data.csv` in this directory — the script will use it if present.
