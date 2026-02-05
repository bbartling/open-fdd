---
title: Expression Rule Cookbook
nav_order: 5
---

# Expression Rule Cookbook

All fault rules in **open-fdd** are listed below. Rules live in [`open_fdd/rules/`](https://github.com/bbartling/open-fdd/tree/master/open_fdd/rules) and can be loaded with `load_rule(path)` or `RuleRunner(rules_path="open_fdd/rules")`.

## Sensor checks (bounds & flatline)

| Rule | Type | Description |
|------|------|-------------|
| `bad_sensor_check` | bounds | Sensor out of range (inspired by SkySpark badSensorCheck) |
| `sensor_flatline` | flatline | Stuck sensor — value does not change over window |

## AHU fault conditions (FC1–FC16)

| Rule | Type | Description |
|------|------|-------------|
| `low_duct_static_at_max_fan` | expression | FC1: Duct static too low with supply fan at max speed |
| `mix_temp_too_low` | expression | FC2: Mix temp too low; should be between OA and RA |
| `mix_temp_too_high` | expression | FC3: Mix temp too high; should be between OA and RA |
| `excessive_ahu_state_changes` | hunting | FC4: Excessive state changes (hunting behavior) |
| `sat_too_low_heating_mode` | expression | FC5: SAT too low in heating mode (broken heating valve) |
| `oa_fraction_airflow_error` | oa_fraction | FC6: OA fraction calc error or airflow not maintained |
| `sat_too_low_full_heating` | expression | FC7: SAT too low in full heating, valve fully open |
| `sat_mat_mismatch_economizer` | expression | FC8: SAT and MAT should be approx equal in economizer |
| `oat_too_high_free_cooling` | expression | FC9: OAT too high in free cooling without mechanical |
| `oat_mat_mismatch_econ_mech` | expression | FC10: OAT and MAT approx equal in econ+mech cooling |
| `oat_mat_mismatch_economizer` | expression | FC11: OAT and MAT approx equal in economizer |
| `sat_too_high_cooling_modes` | expression | FC12: SAT too high in econ+mech or mech-only cooling |
| `sat_too_high_full_cooling` | expression | FC13: SAT too high vs setpoint in full cooling |
| `cooling_coil_drop_when_inactive` | expression | FC14: Temp drop across inactive cooling coil |
| `heating_coil_rise_when_inactive` | expression | FC15: Temp rise across inactive heating coil |
| `erv_effectiveness_fault` | erv_efficiency | FC16: ERV effectiveness outside expected range |

## Chiller plant

| Rule | Type | Description |
|------|------|-------------|
| `pump_diff_pressure_low` | expression | Pump FC1: Diff pressure too low at max pump speed |
| `chw_flow_high_at_max_pump` | expression | Flow FC2: Primary CHW flow too high at max pump |

## Weather station

| Rule | Type | Description |
|------|------|-------------|
| `weather_temp_stuck` | flatline | Temperature sensor stuck at near-constant value |
| `weather_temp_spike` | expression | Unrealistic temperature change between readings |
| `weather_rh_out_of_range` | expression | Relative humidity outside valid range |
| `weather_gust_lt_wind` | expression | Wind gust reported lower than sustained wind |

---

**Rule types:** `bounds` · `flatline` · `expression` · `hunting` · `oa_fraction` · `erv_efficiency`

---

**Next:** [Configuration]({{ "configuration" | relative_url }})
