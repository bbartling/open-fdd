from pathlib import Path

import pandas as pd

from open_fdd import RuleRunner
from open_fdd.engine import load_rule
from open_fdd.reports import (
    analyze_flatline_episodes,
    flatline_period_range,
    print_column_mapping,
    print_flatline_episodes,
    print_summary,
    sensor_cols_from_column_map,
    summarize_fault,
    time_range,
)

script_dir = Path(__file__).parent
csv_path = script_dir / "data_ahu7.csv"
rules_dir = script_dir / "my_rules"

# BRICK class -> CSV column (flatline check: temp sensors only)
# Supply_Air_Static_Pressure_Sensor excluded - legitimately flat when fan off
column_map = {
    "Supply_Air_Temperature_Sensor": "SAT (°F)",
    "Mixed_Air_Temperature_Sensor": "MAT (°F)",
    "Outside_Air_Temperature_Sensor": "OAT (°F)",
    "Return_Air_Temperature_Sensor": "RAT (°F)",
    "Supply_Fan_Speed_Command": "SF Spd Cmd (%)",
}

df = pd.read_csv(csv_path)
df["timestamp"] = pd.to_datetime(df["timestamp"])

runner = RuleRunner(rules=[load_rule(rules_dir / "sensor_flatline.yaml")])

result = runner.run(
    df,
    timestamp_col="timestamp",
    params={"units": "imperial"},
    skip_missing_columns=True,
    column_map=column_map,
)

sensor_cols = sensor_cols_from_column_map(column_map)

flatline_count = int(result["flatline_flag"].sum())

print("Flatline check only")
print_column_mapping("Column mapping", column_map)
print()
print("Results")
print("  Flatline (stuck sensor):", flatline_count, "rows flagged")
print("    Time frame:", time_range(result, "flatline_flag"))
print()

# Per-episode: which BRICK sensor(s) were flat
episodes = analyze_flatline_episodes(
    result,
    flag_col="flatline_flag",
    timestamp_col="timestamp",
    sensor_cols=sensor_cols,
    tolerance=0.000001,
)
print_flatline_episodes(episodes)

print()
print("Analytics")
flatline_range = flatline_period_range(result, window=12)
print_summary(
    summarize_fault(
        result,
        "flatline_flag",
        timestamp_col="timestamp",
        motor_col=column_map["Supply_Fan_Speed_Command"],
        sensor_cols=sensor_cols,
        period_range=flatline_range,
    ),
    title="Flatline fault",
)
