
from pathlib import Path

import pandas as pd

from open_fdd import RuleRunner
from open_fdd.reports import print_summary, summarize_fault, time_range

script_dir = Path(__file__).parent
csv_path = script_dir / "data_ahu7.csv"
rules_dir = script_dir / "rules"

# BRICK class -> CSV column (bounds check: temp + static pressure sensors)
column_map = {
    "Supply_Air_Temperature_Sensor": "SAT (°F)",
    "Mixed_Air_Temperature_Sensor": "MAT (°F)",
    "Outside_Air_Temperature_Sensor": "OAT (°F)",
    "Return_Air_Temperature_Sensor": "RAT (°F)",
    "Supply_Air_Static_Pressure_Sensor": "SA Static Press (inH₂O)",
    "Supply_Fan_Speed_Command": "SF Spd Cmd (%)",
}

df = pd.read_csv(csv_path)
df["timestamp"] = pd.to_datetime(df["timestamp"])

runner = RuleRunner(rules_path=rules_dir)
runner._rules = [r for r in runner._rules if r.get("name") == "bad_sensor_check"]

result = runner.run(
    df,
    timestamp_col="timestamp",
    params={"units": "imperial"},
    skip_missing_columns=True,
    column_map=column_map,
)

# sensor_cols for reports: all sensors (exclude Supply_Fan_Speed_Command)
sensor_cols = {k: v for k, v in column_map.items() if "Sensor" in k}

bounds_count = int(result["bad_sensor_flag"].sum())

print("Bounds check only")
safe_map = {k: v.encode("ascii", "replace").decode() for k, v in column_map.items()}
print("Column mapping:", safe_map)
print()
print("Results")
print("  Bounds (out-of-range):", bounds_count, "rows flagged")
print("    Time frame:", time_range(result, "bad_sensor_flag"))
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
