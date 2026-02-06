---
title: Sensor Bounds Tutorial
nav_order: 10
---


The bounds script checks whether sensor values fall outside valid ranges (e.g. temperature too high or too low). Like the flatline check, it runs in **episodic fashion**—finding each contiguous run of flagged rows and reporting which BRICK sensor(s) were out of bounds in that episode. OOB means "out of bounds." In this context, an OOB sensor is one whose readings fall outside the allowed range (e.g. temperature or pressure outside the configured bounds).

### Metric conversion

Imperial uses °F for temperature and inH2O for pressure. Metric uses °C and Pa.

- **Temperature:** °F → °C: `(F - 32) * 5/9`
- **Pressure:** 1 inH2O ≈ 249 Pa

Example: `[-0.5, 2.5]` inH2O → `[-125, 623]` Pa

```yaml
name: bad_sensor_check
type: bounds
flag: bad_sensor_flag

params:
  units: imperial

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: Supply_Air_Temperature_Sensor
    bounds:
      imperial: [50, 90]
      metric: [10, 32]
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    column: Mixed_Air_Temperature_Sensor
    bounds:
      imperial: [50, 100]
      metric: [10, 38]
  Return_Air_Temperature_Sensor:
    brick: Return_Air_Temperature_Sensor
    column: Return_Air_Temperature_Sensor
    bounds:
      imperial: [60, 100] 
      metric: [16, 38] 
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: Outside_Air_Temperature_Sensor
    bounds:
      imperial: [-40, 120] 
      metric: [-40, 49]    
  Supply_Air_Static_Pressure_Sensor:
    brick: Supply_Air_Static_Pressure_Sensor
    column: Supply_Air_Static_Pressure_Sensor
    bounds:
      imperial: [-0.5, 2.5] 
      metric: [-125, 623]  

```

Run it. Rules load from `my_rules/` — create that folder on your desktop and run from there if you prefer; it doesn't need to be inside the repo.

```bash
cd examples
python check_faults_ahu7_bounds.py
```

## What the script does

**What it does:** RuleRunner loads sensor_bounds.yaml and parses it into a rule dict with type bounds, inputs with bounds.imperial or bounds.metric, and params.units. For each input, the runner uses column_map to map BRICK class to DataFrame column (e.g. Supply_Air_Temperature_Sensor to SAT (°F)). It calls check_bounds(df[col], low, high) using the bounds for the active unit system. A row is flagged if any sensor value is outside [low, high]. The masks from each sensor are combined with |=, so a row is flagged if any sensor is out of bounds. The combined mask is stored as bad_sensor_flag on the result DataFrame. analyze_bounds_episodes finds each contiguous run of bad_sensor_flag=1 and determines which BRICK sensor(s) had values outside bounds in that episode. print_bounds_episodes formats and prints them (first and last N when there are many), including average readings per OOB sensor.

### Bounds script code

```python


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

# Bounds from my_rules (your rules for your deployment)
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


```

### Bounds console output (episodic)

When you run the bounds script with tight tolerances for testing:

```bash

> python .\check_faults_ahu7_bounds.py  
Bounds check only
Column mapping: {'Supply_Air_Temperature_Sensor': 'SAT (?F)', 'Mixed_Air_Temperature_Sensor': 'MAT (?F)', 'Outside_Air_Temperature_Sensor': 'OAT (?F)', 'Return_Air_Temperature_Sensor': 'RAT (?F)', 'Supply_Air_Static_Pressure_Sensor': 'SA Static Press (inH?O)', 'Supply_Fan_Speed_Command': 'SF Spd Cmd (%)'}  

Results
  Bounds (out-of-range): 3146 rows flagged
    Time frame: 2025-01-02 06:30:00 to 2025-04-16 09:00:00


--- Bounds episodes ---
  (138 episodes total, showing first 10 and last 10)

  Episode 1: 2025-01-02 06:30:00 to 2025-01-02 06:30:00 (1 rows)
    BRICK sensors out of bounds: Supply_Air_Temperature_Sensor
    Avg readings: Supply_Air_Temperature_Sensor: 91.15
    Single sensor OOB: Supply_Air_Temperature_Sensor

  Episode 2: 2025-01-03 01:30:00 to 2025-01-03 05:30:00 (17 rows)
    BRICK sensors out of bounds: Return_Air_Temperature_Sensor
    Avg readings: Return_Air_Temperature_Sensor: 59.47
    Single sensor OOB: Return_Air_Temperature_Sensor

  Episode 3: 2025-01-03 06:30:00 to 2025-01-03 06:30:00 (1 rows)
    BRICK sensors out of bounds: Supply_Air_Temperature_Sensor
    Avg readings: Supply_Air_Temperature_Sensor: 95.54
    Single sensor OOB: Supply_Air_Temperature_Sensor

  Episode 4: 2025-01-04 01:30:00 to 2025-01-04 08:30:00 (29 rows)
    BRICK sensors out of bounds: Return_Air_Temperature_Sensor
    Avg readings: Return_Air_Temperature_Sensor: 59.37
    Single sensor OOB: Return_Air_Temperature_Sensor

  Episode 5: 2025-01-04 21:30:00 to 2025-01-04 21:30:00 (1 rows)
    BRICK sensors out of bounds: Return_Air_Temperature_Sensor
    Avg readings: Return_Air_Temperature_Sensor: 59.54
    Single sensor OOB: Return_Air_Temperature_Sensor

  Episode 6: 2025-01-04 22:00:00 to 2025-01-04 22:30:00 (3 rows)
    BRICK sensors out of bounds: Return_Air_Temperature_Sensor
    Avg readings: Return_Air_Temperature_Sensor: 59.79
    Single sensor OOB: Return_Air_Temperature_Sensor

  Episode 7: 2025-01-05 00:15:00 to 2025-01-05 09:00:00 (36 rows)
    BRICK sensors out of bounds: Return_Air_Temperature_Sensor
    Avg readings: Return_Air_Temperature_Sensor: 57.14
    Single sensor OOB: Return_Air_Temperature_Sensor

  Episode 8: 2025-01-06 05:30:00 to 2025-01-06 05:30:00 (1 rows)
    BRICK sensors out of bounds: Supply_Air_Temperature_Sensor
    Avg readings: Supply_Air_Temperature_Sensor: 93.78
    Single sensor OOB: Supply_Air_Temperature_Sensor

  Episode 9: 2025-01-07 04:00:00 to 2025-01-07 04:15:00 (2 rows)
    BRICK sensors out of bounds: Return_Air_Temperature_Sensor
    Avg readings: Return_Air_Temperature_Sensor: 59.89
    Single sensor OOB: Return_Air_Temperature_Sensor

  Episode 10: 2025-01-07 04:45:00 to 2025-01-07 06:15:00 (7 rows)
    BRICK sensors out of bounds: Return_Air_Temperature_Sensor
    Avg readings: Return_Air_Temperature_Sensor: 59.57
    Single sensor OOB: Return_Air_Temperature_Sensor

  ... (118 episodes omitted) ...

  Episode 129: 2025-04-05 17:30:00 to 2025-04-05 18:45:00 (6 rows)
    BRICK sensors out of bounds: Supply_Air_Temperature_Sensor
    Avg readings: Supply_Air_Temperature_Sensor: 91.82
    Single sensor OOB: Supply_Air_Temperature_Sensor

  Episode 130: 2025-04-08 06:00:00 to 2025-04-08 06:15:00 (2 rows)
    BRICK sensors out of bounds: Return_Air_Temperature_Sensor
    Avg readings: Return_Air_Temperature_Sensor: 58.18
    Single sensor OOB: Return_Air_Temperature_Sensor

  Episode 131: 2025-04-10 23:15:00 to 2025-04-11 06:15:00 (29 rows)
    BRICK sensors out of bounds: Return_Air_Temperature_Sensor
    Avg readings: Return_Air_Temperature_Sensor: 54.29
    Single sensor OOB: Return_Air_Temperature_Sensor

  Episode 132: 2025-04-11 19:15:00 to 2025-04-13 10:15:00 (156 rows)
    BRICK sensors out of bounds: Mixed_Air_Temperature_Sensor, Return_Air_Temperature_Sensor
    Avg readings: Mixed_Air_Temperature_Sensor: 51.24, Return_Air_Temperature_Sensor: 49.55

  Episode 133: 2025-04-13 20:45:00 to 2025-04-14 05:15:00 (35 rows)
    BRICK sensors out of bounds: Mixed_Air_Temperature_Sensor, Return_Air_Temperature_Sensor
    Avg readings: Mixed_Air_Temperature_Sensor: 52.99, Return_Air_Temperature_Sensor: 49.36

  Episode 134: 2025-04-14 05:30:00 to 2025-04-14 05:30:00 (1 rows)
    BRICK sensors out of bounds: Return_Air_Temperature_Sensor
    Avg readings: Return_Air_Temperature_Sensor: 57.29
    Single sensor OOB: Return_Air_Temperature_Sensor

  Episode 135: 2025-04-14 18:00:00 to 2025-04-14 18:00:00 (1 rows)
    BRICK sensors out of bounds: Supply_Air_Temperature_Sensor
    Avg readings: Supply_Air_Temperature_Sensor: 90.14
    Single sensor OOB: Supply_Air_Temperature_Sensor

  Episode 136: 2025-04-14 18:15:00 to 2025-04-14 18:30:00 (2 rows)
    BRICK sensors out of bounds: Supply_Air_Temperature_Sensor
    Avg readings: Supply_Air_Temperature_Sensor: 90.32
    Single sensor OOB: Supply_Air_Temperature_Sensor

  Episode 137: 2025-04-15 22:15:00 to 2025-04-16 06:15:00 (31 rows)
    BRICK sensors out of bounds: Return_Air_Temperature_Sensor
    Avg readings: Return_Air_Temperature_Sensor: 54.24
    Single sensor OOB: Return_Air_Temperature_Sensor

  Episode 138: 2025-04-16 06:30:00 to 2025-04-16 09:00:00 (11 rows)
    BRICK sensors out of bounds: Mixed_Air_Temperature_Sensor, Return_Air_Temperature_Sensor
    Avg readings: Mixed_Air_Temperature_Sensor: 55.32, Return_Air_Temperature_Sensor: 52.43

Analytics

--- Bounds fault ---
  total days: 105.39
  total hours: 2529
  hours bad sensor mode: 785
  percent true: 30.8
  percent false: 69.2
  percent hours true: 31.03
  hours motor runtime: 860.3
  flag true Supply Air Temperature Sensor: 103.62
  flag true Mixed Air Temperature Sensor: 59.44
  flag true Outside Air Temperature Sensor: 64.22
  flag true Return Air Temperature Sensor: 67.41
  flag true Supply Air Static Pressure Sensor: 0.03
  fault period start: 2025-01-02 06:30:00
  fault period end: 2025-04-16 09:00:00
  fault period days: 104.1
  fault period hours: 2498
  fault period rows: 10090
  fault period rows flagged: 3146
  fault period percent true: 31.18

```

---

**Next:** [SPARQL & Validate Prereq]({{ "sparql_validate_prereq" | relative_url }}) — test SPARQL, validate model before running faults
