---
title: Machine Learning for FDD — Ideas & Roadmap
nav_order: 20
---


# Machine Learning for FDD (Ideas)

These are **future enhancements** for open-fdd to complement rule-based fault detection with data-driven methods.

**Rules** remain the foundation because they are physics-based, interpretable, and easy to validate.
**Machine learning** can add value by learning normal behavior, detecting unknown faults, and reducing false positives.

Potential additions include:

* Anomaly detection on telemetry
* Anomaly detection on rule outputs (fault patterns)
* Clustering to group similar fault events
* Simple regression/classification for performance modeling

The goal is a **hybrid approach**: rules for known problems, ML to surface unusual or emerging issues — keeping results transparent and engineer-friendly.


## Physics Based ML Regression models

**Concept:** Train a regression model to predict supply fan motor speed from zone-level and AHU-level inputs. If the model is well-calibrated, predicted vs actual fan speed within tolerance indicates normal operation; deviation beyond tolerance flags a potential fault. Results can be compared with open-fdd rule-based faults.

**Example — VAV AHU with zone data:**

| Input (features) | Target |
|------------------|--------|
| `Damper_Position_Command` (VAV 1..N; use `column_map` keys like `Damper_Position_Command` + zone id) | `Supply_Fan_Speed_Command` |
| `Zone_Air_Temperature_Sensor`, `Zone_Temperature_Setpoint` | |
| `Supply_Air_Temperature_Sensor`, `Supply_Air_Temperature_Setpoint` | |
| `Supply_Air_Static_Pressure_Sensor`, `Supply_Air_Static_Pressure_Setpoint` | |
| `Outside_Air_Temperature_Sensor`, `Mixed_Air_Temperature_Sensor`, `Return_Air_Temperature_Sensor` | |
| `Valve_Command` (heating, cooling — disambiguate via `Valve_Command` + rule_input in `column_map`) | |

**Workflow:**

1. **Data:** Time-series DataFrame with AHU + zone columns (e.g. from Brick model + CSV). Align to common timestamps.
2. **Train:** Fit a model (e.g. Gradient Boosting, Random Forest, or simple neural net) on "normal" periods — exclude known fault intervals if labeled.
3. **Predict:** Generate `fan_speed_pred` for each timestamp.
4. **Fault flag:** `ml_fan_speed_fault = |Supply_Fan_Speed_Command - fan_speed_pred| > tolerance`
5. **Compare:** Join `ml_fan_speed_fault` with open-fdd rule flags (`rule_a_flag`, `rule_b_flag`, etc.). Correlate ML faults with rule faults; ML may catch deviations rules miss (e.g. subtle efficiency drift), while rules catch known conditions (e.g. duct static low at full speed).

**Pseudocode with open-fdd:**

```python
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from open_fdd import RuleRunner

# 1. Load data (AHU + zone columns)
df = pd.read_csv("vav_ahu_zone_data.csv", parse_dates=["timestamp"])

# 2. Run rule-based FDD
runner = RuleRunner(rules_path="open_fdd/rules")
result = runner.run(df, column_map=column_map)
# result has rule_a_flag, rule_b_flag, ...

# 3. Train ML model (features = BRICK classes; column_map resolves to df columns)
# Use column_map keys: Damper_Position_Command|zone1, Zone_Air_Temperature_Sensor, etc.
feature_cols = ["Damper_Position_Command|zone1", "Damper_Position_Command|zone2", ...,
                "Supply_Air_Temperature_Sensor", "Supply_Air_Temperature_Setpoint",
                "Supply_Air_Static_Pressure_Sensor", "Outside_Air_Temperature_Sensor",
                "Mixed_Air_Temperature_Sensor", "Return_Air_Temperature_Sensor",
                "Valve_Command|heating_sig", "Valve_Command|cooling_sig"]
X = df[[column_map[c] for c in feature_cols if c in column_map]]
y = df[column_map["Supply_Fan_Speed_Command"]]
model = GradientBoostingRegressor().fit(X, y)

# 4. Predict and flag
result["fan_speed_pred"] = model.predict(X)
tolerance = 0.05  # 5% deviation
result["ml_fan_speed_fault"] = (result[column_map["Supply_Fan_Speed_Command"]] - result["fan_speed_pred"]).abs() > tolerance

# 5. Compare ML vs rule faults
# e.g. result[["rule_a_flag", "rule_b_flag", "ml_fan_speed_fault"]].corr()
# or: during ml_fan_speed_fault, what % also have rule_a_flag?
```

**Use case:** Detect fan/system anomalies that rules may not explicitly cover (e.g. control drift, partial damper failures, unexpected interaction between zones). Good model fit implies the system behaves as expected; poor fit suggests something changed.

---



**Status:** Ideas only. No ML code in open-fdd core yet. Contributions welcome.
