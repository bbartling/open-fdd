
from pathlib import Path

import pandas as pd

from open_fdd import RuleRunner
from open_fdd.reports import (
    analyze_flatline_episodes,
    flatline_period,
    flatline_period_range,
    print_flatline_episodes,
    print_summary,
    summarize_fault,
    time_range,
)

script_dir = Path(__file__).parent
csv_path = script_dir / "data_ahu7.csv"
rules_dir = script_dir / "rules"

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

runner = RuleRunner(rules_path=rules_dir)
runner._rules = [r for r in runner._rules if r.get("name") == "sensor_flatline"]

result = runner.run(
    df,
    timestamp_col="timestamp",
    params={"units": "imperial"},
    skip_missing_columns=True,
    column_map=column_map,
)

# sensor_cols for episode analysis: all sensors (exclude Supply_Fan_Speed_Command)
sensor_cols = {k: v for k, v in column_map.items() if "Sensor" in k}

flatline_count = int(result["flatline_flag"].sum())

print("Flatline check only")
safe_map = {k: v.encode("ascii", "replace").decode() for k, v in column_map.items()}
print("Column mapping:", safe_map)
print()
print("Results")
print("  Flatline (stuck sensor):", flatline_count, "rows flagged")
print("    Time frame (data flat):", flatline_period(result))
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
