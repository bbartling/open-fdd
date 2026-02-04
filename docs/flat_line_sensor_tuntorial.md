---
title: Flat Line Sensor Tutorial
nav_order: 3
---


Every fault rule in **open-fdd** is now configuration-driven in Version 2. When the Python code below runs, it reads settings from a YAML file that defines which sensors to evaluate and what parameters to use. For each sensor, the algorithm checks whether the reading changes within a specified tolerance over a rolling 12-sample window and flags rows where the difference between the maximum and minimum values is less than the tolerance.

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


(Supply Air Static Pressure is excluded from flatline—it is legitimately flat when the fan is off but included in the next tutorial for a sensor bounds check.)

The `examples/data_ahu7.csv` file (~10k rows) is included in the repository. The `check_faults_ahu7_flatline.py` script runs bounds and flatline checks on this data and prints the fault counts. Try it yourself.

The data set has been artififially modified for flat lined values on all rows in a 3 hour time frame which could mimic a BAS/BMS device being offline.

```csv
2025-01-01 02:00:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,65.06600189208984,45.50650024414063,62.3120002746582,61.64599990844727,,,,,,,,
2025-01-01 02:15:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,64.68800354003906,45.11940002441406,61.80799865722656,61.555999755859375,,,,,,,,
2025-01-01 02:30:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,64.50800323486328,44.67440032958984,61.46599960327149,61.46599960327149,,,,,,,,
2025-01-01 02:45:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,64.22000122070312,44.51440048217773,61.93399810791016,61.30400085449219,,,,,,,,
2025-01-01 03:00:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 03:15:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 03:45:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 04:00:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 04:15:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 04:30:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 04:45:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 05:00:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 05:15:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 05:30:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 05:45:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 06:00:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 06:15:00,0.0,0.0,100.0,0.0,0.0,0.0,0.0268750004470348,70.0,75.75800323486328,44.99039840698242,61.141998291015625,60.79999923706055,,,,,,,,
2025-01-01 06:26:00,,,,,,,,,,,,,,,,,1.0,,,
```

There are also real instances in the dataset where the BAS supervisory controller fails to update the outside air networked temperature value on the AHU7 controller. The fault rule detects these conditions and reports them as `episodes`, representing the number of separate times the sensor stops updating.


When you run the script.

```bash
cd examples
python check_faults_ahu7_flatline.py
```


## What the script does


What it does: It finds each contiguous flatline episode in the data, checks which BRICK sensors were flat (spread &lt; tolerance) in that episode, and returns a list of episode dicts with start/end times, which sensors were flat, and flags for “all sensors flat” (device offline) vs “single sensor flat” (controller not writing).


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
    Time frame (data flat): 2025-01-01 03:00:00 to 2025-02-28 06:15:00

First 3 flagged rows (SAT, MAT, OAT, RAT):
  2025-01-01 06:00:00: SAT=60.80 MAT=75.76 OAT=44.99 RAT=61.14
  2025-01-01 06:15:00: SAT=60.80 MAT=75.76 OAT=44.99 RAT=61.14
  2025-01-05 04:45:00: SAT=66.33 MAT=93.45 OAT=21.00 RAT=56.57
Last 3 flagged rows:
  2025-02-28 05:45:00: SAT=76.89 MAT=57.92 OAT=70.00 RAT=69.08
  2025-02-28 06:00:00: SAT=88.02 MAT=58.95 OAT=70.00 RAT=69.42
  2025-02-28 06:15:00: SAT=97.25 MAT=60.24 OAT=70.00 RAT=69.75

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
PS C:\Users\ben\Documents\open-fdd\examples> python .\check_faults_ahu7_flatline.py
Flatline check only
Column mapping: {'Supply_Air_Temperature_Sensor': 'SAT (°F)', 'Mixed_Air_Temperature_Sensor': 'MAT (°F)', 'Outside_Air_Temperature_Sensor': 'OAT (°F)', 'Return_Air_Temperature_Sensor': 'RAT (°F)', 'Supply_Fan_Speed_Command': 'SF Spd Cmd (%)'}

Results
  Flatline (stuck sensor): 3926 rows flagged
    Time frame (data flat): 2025-01-01 03:00:00 to 2025-02-28 06:15:00


--- Flatline episodes ---
  (76 episodes total, showing first 10 and last 10)

  Episode 1: 2025-01-01 06:00:00 to 2025-01-01 06:15:00 (2 rows)
    BRICK sensors flat: Supply_Air_Temperature_Sensor, Mixed_Air_Temperature_Sensor, Outside_Air_Temperature_Sensor, Return_Air_Temperature_Sensor
    All sensors flat: Yes (device offline)

  Episode 2: 2025-01-05 04:45:00 to 2025-01-05 08:45:00 (17 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 3: 2025-01-09 10:30:00 to 2025-01-09 18:00:00 (29 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 4: 2025-01-09 21:00:00 to 2025-01-10 06:15:00 (38 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 5: 2025-01-10 09:30:00 to 2025-01-10 18:00:00 (35 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 6: 2025-01-10 21:00:00 to 2025-01-13 05:15:00 (225 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 7: 2025-01-13 08:15:00 to 2025-01-13 18:00:00 (40 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 8: 2025-01-13 21:00:00 to 2025-01-14 06:15:00 (38 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 9: 2025-01-14 09:15:00 to 2025-01-14 18:00:00 (36 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 10: 2025-01-14 21:00:00 to 2025-01-15 06:15:00 (38 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  ... (56 episodes omitted) ...

  Episode 67: 2025-02-21 21:00:00 to 2025-02-21 21:00:00 (1 rows)
    BRICK sensors flat: (none)

  Episode 68: 2025-02-22 00:00:00 to 2025-02-24 05:15:00 (212 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 69: 2025-02-24 08:15:00 to 2025-02-24 18:00:00 (40 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 70: 2025-02-24 21:00:00 to 2025-02-25 06:15:00 (37 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 71: 2025-02-25 09:15:00 to 2025-02-25 16:00:00 (26 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 72: 2025-02-25 21:00:00 to 2025-02-26 06:15:00 (37 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 73: 2025-02-26 09:15:00 to 2025-02-26 18:00:00 (34 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 74: 2025-02-26 21:00:00 to 2025-02-27 06:15:00 (38 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 75: 2025-02-27 09:15:00 to 2025-02-27 18:00:00 (36 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

  Episode 76: 2025-02-27 21:00:00 to 2025-02-28 06:15:00 (38 rows)
    BRICK sensors flat: Outside_Air_Temperature_Sensor
    Single sensor flat: Outside_Air_Temperature_Sensor (controller not writing)

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

**Next:** [Sensor Bounds Check Tutorial](bounds_sensor_tuntorial.md)
