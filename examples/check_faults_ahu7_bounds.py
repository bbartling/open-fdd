from pathlib import Path

import pandas as pd

from open_fdd import RuleRunner
from open_fdd.engine import bounds_map_from_rule, load_rule
from open_fdd.reports import (
    analyze_bounds_episodes,
    print_bounds_episodes,
    print_column_mapping,
    print_summary,
    sensor_cols_from_column_map,
    summarize_fault,
    time_range,
)

script_dir = Path(__file__).parent
csv_path = script_dir / "data_ahu7.csv"
rules_dir = script_dir / "my_rules"

# BRICK class -> CSV column (bounds check: temp + static pressure sensors)
column_map = {
    "Supply_Air_Temperature_Sensor": "SAT (°F)",
    "Mixed_Air_Temperature_Sensor": "MAT (°F)",
    "Outside_Air_Temperature_Sensor": "OAT (°F)",
    "Return_Air_Temperature_Sensor": "RAT (°F)",
    "Supply_Air_Static_Pressure_Sensor": "SA Static Press (inH₂O)",
    "Supply_Fan_Speed_Command": "SF Spd Cmd (%)",
}

# Bounds from YAML (single source of truth)
bounds_rule = load_rule(rules_dir / "sensor_bounds.yaml")
bounds_map = bounds_map_from_rule(bounds_rule, units="imperial")

df = pd.read_csv(csv_path)
df["timestamp"] = pd.to_datetime(df["timestamp"])

runner = RuleRunner(rules=[load_rule(rules_dir / "sensor_bounds.yaml")])

result = runner.run(
    df,
    timestamp_col="timestamp",
    params={"units": "imperial"},
    skip_missing_columns=True,
    column_map=column_map,
)

sensor_cols = sensor_cols_from_column_map(column_map)

bounds_count = int(result["bad_sensor_flag"].sum())

print("Bounds check only")
print_column_mapping("Column mapping", column_map)
print()
print("Results")
print("  Bounds (out-of-range):", bounds_count, "rows flagged")
print("    Time frame:", time_range(result, "bad_sensor_flag"))
print()

# Per-episode: which BRICK sensor(s) were out of bounds
episodes = analyze_bounds_episodes(
    result,
    flag_col="bad_sensor_flag",
    timestamp_col="timestamp",
    sensor_cols=sensor_cols,
    bounds_map=bounds_map,
)
print_bounds_episodes(episodes)

print()
print("Analytics")
print_summary(
    summarize_fault(
        result,
        "bad_sensor_flag",
        timestamp_col="timestamp",
        motor_col=column_map["Supply_Fan_Speed_Command"],
        sensor_cols=sensor_cols,
    ),
    title="Bounds fault",
)
