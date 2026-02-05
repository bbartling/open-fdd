---
title: Flat Line Sensor Tutorial
nav_order: 3
---


Every fault rule in **open-fdd** is now configuration-driven in Version 2 in the form of a YAML file as shown below. When the Python code below runs, it reads settings from a YAML file that defines which sensors to evaluate and what parameters to use. For each sensor, the algorithm checks whether the reading changes within a specified tolerance over a rolling 12-sample window and flags rows where the difference between the maximum and minimum values is less than the tolerance.

The masks from each sensor are then combined using the `|=` operator, so a row is flagged if any sensor appears flat. Finally, the combined mask is written to the result DataFrame as a new column called `flatline_flag`.

In short, the YAML defines the sensors and parameters, the runner maps them to DataFrame columns through `column_map`, applies `check_flatline` to each signal, ORs the results together, and adds `flatline_flag` to the output.



```yaml
name: sensor_flatline
type: flatline
flag: flatline_flag

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: Supply_Air_Temperature_Sensor
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    column: Mixed_Air_Temperature_Sensor
  Return_Air_Temperature_Sensor:
    brick: Return_Air_Temperature_Sensor
    column: Return_Air_Temperature_Sensor
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: Outside_Air_Temperature_Sensor

params:
  tolerance: 0.000001
  window: 12
```


> For this tutorial the supply air static pressure is excluded from flatline as it is legitimately flat when the fan is off but included in the next tutorial for a sensor bounds check.

The tutorial uses `data_ahu7.csv` (~10k rows). Place it in the [examples directory](https://github.com/bbartling/open-fdd/tree/master/examples) (see the README there for how to obtain it). The scripts load rules from `my_rules/` — your rules folder. Create a `my_rules` folder on your desktop (or anywhere) and run the tutorial from there; it doesn't need to be inside the repo. `check_faults_ahu7_flatline.py` and `check_faults_ahu7_bounds.py` run flatline and bounds checks on this data. Try it yourself.

The data set has been artificially modified for flat lined values on all rows in a 3 hour time frame which could mimic a BAS/BMS device being offline.

```csv
2025-01-01 02:00:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,65.06600189208984,45.50650024414063,62.3120002746582,61.64599990844727,,,,,,,,
2025-01-01 02:15:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,64.68800354003906,45.11940002441406,61.80799865722656,61.555999755859375,,,,,,,,
2025-01-01 02:30:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,64.50800323486328,44.67440032958984,61.46599960327149,61.46599960327149,,,,,,,,

...

2025-01-01 05:45:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 06:00:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 06:15:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
```

## Episodes

There are also real instances in the dataset where the BAS supervisory controller fails to update the networked outside-air temperature value on the AHU7 controller. The fault rule detects these conditions and reports them as `episodes` — each episode represents a separate period when the sensor stops updating.


When you run the script.

```bash
cd examples
python check_faults_ahu7_flatline.py
```


## What the script does

**What it does:** It finds each contiguous flatline episode in the data, checks which BRICK sensors were flat lined in that episode, and returns a list of episode dicts with start/end times, which sensors were flat, and flags for “all sensors flat” (device offline) vs “single sensor flat” (controller not updating).


```python


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

```


In the console this will print back this below which was ran on PowerShell and Windows.

```bash
> python .\check_faults_ahu7_flatline.py
Flatline check only
Column mapping: {'Supply_Air_Temperature_Sensor': 'SAT (°F)', 'Mixed_Air_Temperature_Sensor': 'MAT (°F)', 'Outside_Air_Temperature_Sensor': 'OAT (°F)', 'Return_Air_Temperature_Sensor': 'RAT (°F)', 'Supply_Fan_Speed_Command': 'SF Spd Cmd (%)'}

Results
  Flatline (stuck sensor): 3926 rows flagged
    Time frame: 2025-01-01 06:00:00 to 2025-02-28 06:15:00


--- Flatline episodes ---
  (76 episodes total, showing first 10 and last 10)

  Episode 1: 2025-01-01 06:00:00 to 2025-01-01 06:15:00 (2 rows)
    BRICK sensors flat: Supply_Air_Temperature_Sensor, Mixed_Air_Temperature_Sensor, Outside_Air_Temperature_Sensor, Return_Air_Temperature_Sensor        
    Last 3 values: Supply_Air_Temperature_Sensor: [60.8, 60.8], Mixed_Air_Temperature_Sensor: [75.76, 75.76], Outside_Air_Temperature_Sensor: [44.99, 44.99], Return_Air_Temperature_Sensor: [61.14, 61.14]
    All sensors flat: Yes (device offline)

  Episode 2: 2025-01-05 04:45:00 to 2025-01-05 08:45:00 (17 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [21.0, 21.0, 21.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 3: 2025-01-09 10:30:00 to 2025-01-09 18:00:00 (29 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 4: 2025-01-09 21:00:00 to 2025-01-10 06:15:00 (38 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 5: 2025-01-10 09:30:00 to 2025-01-10 18:00:00 (35 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 6: 2025-01-10 21:00:00 to 2025-01-13 05:15:00 (225 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 7: 2025-01-13 08:15:00 to 2025-01-13 18:00:00 (40 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 8: 2025-01-13 21:00:00 to 2025-01-14 06:15:00 (38 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 9: 2025-01-14 09:15:00 to 2025-01-14 18:00:00 (36 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 10: 2025-01-14 21:00:00 to 2025-01-15 06:15:00 (38 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  ... (56 episodes omitted) ...

  Episode 67: 2025-02-21 21:00:00 to 2025-02-21 21:00:00 (1 rows)
    BRICK sensors flat: (none)

  Episode 68: 2025-02-22 00:00:00 to 2025-02-24 05:15:00 (212 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 69: 2025-02-24 08:15:00 to 2025-02-24 18:00:00 (40 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 70: 2025-02-24 21:00:00 to 2025-02-25 06:15:00 (37 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 71: 2025-02-25 09:15:00 to 2025-02-25 16:00:00 (26 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 72: 2025-02-25 21:00:00 to 2025-02-26 06:15:00 (37 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 73: 2025-02-26 09:15:00 to 2025-02-26 18:00:00 (34 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 74: 2025-02-26 21:00:00 to 2025-02-27 06:15:00 (38 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 75: 2025-02-27 09:15:00 to 2025-02-27 18:00:00 (36 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

  Episode 76: 2025-02-27 21:00:00 to 2025-02-28 06:15:00 (38 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Last 3 values: Outside_Air_Temperature_Sensor: [70.0, 70.0, 70.0]
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not updating)

Analytics

--- Flatline fault ---
  total days: 105.39
  total hours: 2529
  hours flatline mode: 992
  percent true: 38.44
  percent false: 61.56
  percent hours true: 39.22
  hours motor runtime: 860.3
  flag true Supply Air Temperature Sensor: 93.74
  flag true Mixed Air Temperature Sensor: 60.39
  flag true Outside Air Temperature Sensor: 69.78
  flag true Return Air Temperature Sensor: 71.13
  fault period start: 2025-01-01 03:00:00
  fault period end: 2025-02-28 06:15:00
  fault period days: 58.14
  fault period hours: 1395
  fault period rows: 5636
  fault period rows flagged: 3926
  fault period percent true: 69.66
```


---

**Next:** [Sensor Bounds Check Tutorial]({{ "bounds_sensor_tuntorial" | relative_url }})
