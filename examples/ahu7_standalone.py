"""Run open-fdd sensor checks (bounds + flatline) on AHU7 data — no open-fdd-core needed.

Uses the packaged examples/ahu7_sample.csv (500 rows, ~80KB). For full dataset,
download ahu7_data.csv and place next to this script.
"""
import pandas as pd
from pathlib import Path

import open_fdd
from open_fdd import RuleRunner

# Prefer full ahu7_data.csv if present; otherwise use packaged sample
script_dir = Path(__file__).parent
csv_path = script_dir / "ahu7_data.csv"
if not csv_path.exists():
    csv_path = script_dir / "ahu7_sample.csv"

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

rules_dir = Path(open_fdd.__file__).parent / "rules"
runner = RuleRunner(rules_path=rules_dir)
runner._rules = [
    r for r in runner._rules
    if r.get("name") in ("bad_sensor_check", "sensor_flatline")
]

# Imperial (AHU7 data is °F)
result = runner.run(
    df, timestamp_col="timestamp",
    params={"units": "imperial"},
    skip_missing_columns=True,
)
print("Bounds (imperial):", result["bad_sensor_flag"].sum(), "faults")
print("Flatline:", result["flatline_flag"].sum(), "faults")
