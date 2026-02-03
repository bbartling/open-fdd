"""Run open-fdd on AHU7 data — BRICK model driven.

Uses examples/ahu7_brick_model.ttl to resolve rule inputs from the Brick schema.
Column mapping comes from ofdd:mapsToRuleInput + rdfs:label in the TTL.

Requires: pip install open-fdd[brick]  # for Brick resolution
"""

import pandas as pd
from pathlib import Path

import open_fdd
from open_fdd import RuleRunner

script_dir = Path(__file__).parent
ttl_path = script_dir / "ahu7_brick_model.ttl"
csv_path = script_dir / "ahu7_data.csv"
if not csv_path.exists():
    csv_path = script_dir / "ahu7_sample.csv"

df = pd.read_csv(csv_path)
df["timestamp"] = pd.to_datetime(df["timestamp"])

# Resolve column map from Brick TTL (rule_input -> CSV column)
import sys

sys.path.insert(0, str(script_dir))
try:
    from brick_resolver import resolve_from_ttl

    column_map = resolve_from_ttl(ttl_path)
    print("BRICK-driven column map:", list(column_map.keys()))
except ImportError:
    # Fallback: manual mapping when rdflib not installed
    column_map = {
        "sat": "SAT (°F)",
        "mat": "MAT (°F)",
        "oat": "OAT (°F)",
        "rat": "RAT (°F)",
    }
    print("Using fallback column map (install open-fdd[brick] for BRICK resolution)")

rules_dir = Path(open_fdd.__file__).parent / "rules"
runner = RuleRunner(rules_path=rules_dir)
runner._rules = [
    r for r in runner._rules if r.get("name") in ("bad_sensor_check", "sensor_flatline")
]

result = runner.run(
    df,
    timestamp_col="timestamp",
    params={"units": "imperial"},
    skip_missing_columns=True,
    column_map=column_map,
)
print("Bounds (imperial):", result["bad_sensor_flag"].sum(), "faults")
print("Flatline:", result["flatline_flag"].sum(), "faults")
