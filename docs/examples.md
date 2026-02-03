# Examples

**open-fdd** runs standalone — no open-fdd-core needed. You only need pandas and a DataFrame. Use open-fdd-core when you want TimescaleDB, Brick TTL, and a web API.

**Try it:** The repo includes `examples/ahu7_sample.csv` (500 rows, ~80KB) and `examples/ahu7_standalone.py`:
```bash
cd open-fdd
python examples/ahu7_standalone.py
```
For the full dataset (~10k rows), place `ahu7_data.csv` in `examples/` — the script uses it if present.

---

## Rule definitions: bad data (bounds) and flatline

Rules live in `open_fdd/rules/` as YAML. Here’s how the sensor checks are defined:

### Bad data (bounds) — `sensor_bounds.yaml`

Faults when a value is outside the configured range (e.g. bad sensor or bad data):

```yaml
name: bad_sensor_check
type: bounds
flag: bad_sensor_flag

params:
  units: imperial   # override at runtime: params={"units": "metric"}

inputs:
  supply_air_temp:
    column: sat
    bounds:
      imperial: [40, 150]    # degF
      metric: [4, 66]        # degC
  return_air_temp:
    column: rat
    bounds:
      imperial: [40, 100]
      metric: [4, 38]
  # ... mat, oat, rh, etc.
```

### Flatline — `sensor_flatline.yaml`

Faults when a sensor value barely changes over a rolling window (stuck sensor):

```yaml
name: sensor_flatline
type: flatline
flag: flatline_flag

inputs:
  supply_air_temp:
    column: sat
  zone_temp:
    column: zt

params:
  tolerance: 0.000001   # rolling spread must exceed this
  window: 12            # number of samples (e.g. 12 x 15min = 3hr)
```

---

## Sensor checks on AHU7 data (bounds + flatline)

Bounds (imperial) and flatline detection. Uses `examples/ahu7_sample.csv` or `ahu7_data.csv`:

```python
import pandas as pd
from pathlib import Path

import open_fdd
from open_fdd import RuleRunner

# Load AHU7 CSV (ahu7_data.csv or ahu7_sample.csv in examples/)
csv_path = Path(__file__).parent / "ahu7_data.csv"
if not csv_path.exists():
    csv_path = Path(__file__).parent / "ahu7_sample.csv"
df = pd.read_csv(csv_path)
df["timestamp"] = pd.to_datetime(df["timestamp"])

# Map AHU7 column names to rule input names
rename = {
    "SAT (°F)": "sat",
    "MAT (°F)": "mat",
    "OAT (°F)": "oat",
    "RAT (°F)": "rat",
}
df = df.rename(columns=rename)

# Rules directory (from installed package)
rules_dir = Path(open_fdd.__file__).parent / "rules"
runner = RuleRunner(rules_path=rules_dir)

# Run only sensor rules (bounds + flatline)
runner._rules = [
    r for r in runner._rules
    if r.get("name") in ("bad_sensor_check", "sensor_flatline")
]

# Imperial (AHU7 data is °F): SAT 40–150 °F, MAT/RAT/OAT 40–100 °F, etc.
result = runner.run(
    df, timestamp_col="timestamp",
    params={"units": "imperial"},
    skip_missing_columns=True,
)
print("Bounds (imperial):", result["bad_sensor_flag"].sum(), "faults")
print("Flatline:", result["flatline_flag"].sum(), "faults")
```

**How to change units:** Pass `params={"units": "metric"}` for °C bounds. Your DataFrame values must already be in that unit (no auto-conversion). AHU7 data is °F — use `params={"units": "imperial"}` (or omit; imperial is default). To switch to metric, convert your temps to °C first, then pass `params={"units": "metric"}`.

---

## Minimal standalone (no CSV, in-memory)

```python
import pandas as pd
from open_fdd import RuleRunner

df = pd.DataFrame({
    "timestamp": pd.date_range("2024-01-01", periods=100, freq="15min"),
    "sat": [55.0] * 100,      # flatline
    "mat": [60.0] * 100,
    "oat": [45.0] * 100,
    "rat": [70.0] * 100,
})

runner = RuleRunner("open_fdd/rules")  # or Path(open_fdd.__file__).parent / "rules"
result = runner.run(df, timestamp_col="timestamp", skip_missing_columns=True)

# Sensor checks
print("bad_sensor_flag:", result["bad_sensor_flag"].sum())
print("flatline_flag:", result["flatline_flag"].sum())
```

---


