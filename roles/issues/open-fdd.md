> **PRIORITY: ASAP, owner directive.** Unify Open-FDD's three role vocabularies (input_contract.json, the #1808 manifest, the #1807 OpenAPI) on roles/openfdd-roles.json (strict ASHRAE 223P plus exact Haystack 4 mapping) before any other 5.0.22 rule work. Includes renaming \*_position inputs that are bound to command points, and fixing unit mismatches (0-1 vs %, L/s vs m3/s).

**Title:** Migrate rule inputs to `roles/openfdd-roles.json` and fix the MIT LICENSE (5.0.22 gate)

## Problem

Open-FDD has three rule-input vocabularies that disagree:

| Source | Names | Units |
|---|---|---|
| `sql/fdd/input_contract.json` (75 keys) | short keys (`oa_damper_pct`, `fan_cmd`) | `fraction` (0-1), `si:degC`, `boolean`, `text` |
| #1808 bundle manifest (`sql/fdd/input_names_223p.json`, `scripts/build_rules_bundle.py`) | "223P-derived" names chosen by hand | `SCALE_UNIT`; manifest `haystack` field is a `role_map.json` label |
| #1807 OpenAPI (`openapi/open-fdd-ui-api.yaml`) | `InputName` table (14 rows) | `SiUnit` Haystack symbols (`°C`, `%`, `L/s`) |

The audit found these defects:

- **Position names on command points.** `outside_air_damper_position`, `cooling_valve_position` and `heating_valve_position` (#1808 and #1807) are bound to `cmd` points. Today `damper_pct` accepts the `damper-cmd` class, `oa_damper_pct` takes either `outside-damper-cmd` or `outside-damper-sensor`, and `loop_enabled` (a status) binds `enable-cmd`.
- **Ratio units.** Ratios are 0-1 in Open-FDD and 0-100 in the other two apps. The edge stores flow in m3/s; Open-FDD uses L/s.
- **Binding gaps.** Setpoint bindings do not forbid `max`/`min`, so an airflow maximum can bind as the airflow setpoint.
- **Fan speed.** `FC1` reads `fan_cmd` (a start/stop command) as a VFD speed.
- **LICENSE.** The MIT `LICENSE` is truncated: it has no holder, no conditions and no warranty disclaimer.

`roles/openfdd-roles.json` (89 roles, 72 pure 223P and 17 extensions; see `roles/README.md`) replaces all three.

## Gate

5.0.22 is not tagged until every acceptance criterion below holds. No other 5.0.22 rule work merges before this
issue.

## Renames

Every `input_contract.json` key, the name #1808 gave it, and the canonical role. The roles file records each old key in
`legacy_keys` and each old name in `aliases`.

<details><summary>75 renames</summary>

| `input_contract.json` key | #1808 name | Canonical role | Scale -> unit |
|---|---|---|---|
| `ahu_sat` | `air_handling_unit_discharge_air_temperature` | `air_handling_unit_discharge_air_temperature` | `DEG_C` |
| `building_ahu_load_satisfied` | `building_air_handling_unit_load_satisfied` | `air_handling_unit_load_satisfied_status` | `boolean` |
| `building_zone_load_satisfied` | `building_zone_load_satisfied` | `zone_load_satisfied_status` | `boolean` |
| `chiller_amps` | `chiller_electric_current_magnitude` | `chiller_electric_current` | `A` |
| `chiller_cmd` | `chiller_command` | `chiller_command` | **`fraction` -> `boolean`** |
| `chiller_current` | `chiller_electric_current` | `chiller_electric_current` | `A` |
| `chiller_power` | `chiller_electric_power` | `chiller_electric_power` | `KiloW` |
| `chiller_status` | `chiller_run_status` | `chiller_operating_status` | `boolean` |
| `chw_dp` | `chilled_water_differential_pressure` | `chilled_water_pressure_delta` | `PA` |
| `chw_dp_sp` | `chilled_water_differential_pressure_setpoint` | `chilled_water_pressure_delta_setpoint` | `PA` |
| `chw_flow` | `chilled_water_flow` | `chilled_water_volume_flow_rate` | `L-PER-SEC` |
| `chw_pump_cmd` | `chilled_water_pump_command` | `chilled_water_pump_command` | **`fraction` -> `boolean`** |
| `chw_pump_status` | `chilled_water_pump_run_status` | `chilled_water_pump_operating_status` | `boolean` |
| `chw_reset_request_sum` | `chilled_water_reset_request_count` | `chilled_water_reset_request_count` | `NUM` |
| `chw_return_t` | `chilled_water_return_temperature` | `return_chilled_water_temperature` | `DEG_C` |
| `chw_supply_sp` | `chilled_water_supply_temperature_setpoint` | `supply_chilled_water_temperature_setpoint` | `DEG_C` |
| `chw_supply_t` | `chilled_water_supply_temperature` | `supply_chilled_water_temperature` | `DEG_C` |
| `clg_available` | `cooling_available` | `cooling_operating_mode_status` | `boolean` |
| `clg_valve_pct` | `cooling_valve_position` | `cooling_valve_position_command` | **`fraction` -> `PERCENT` (x100)** |
| `compressor_status` | `compressor_run_status` | `compressor_operating_status` | `boolean` |
| `cooling_coil_entering_temp` | `cooling_coil_entering_temperature` | `cooling_coil_inlet_air_temperature` | `DEG_C` |
| `cooling_coil_leaving_temp` | `cooling_coil_leaving_temperature` | `cooling_coil_outlet_air_temperature` | `DEG_C` |
| `cooling_sp` | `cooling_temperature_setpoint` | `zone_cooling_air_temperature_setpoint` | `DEG_C` |
| `cw_pump_cmd` | `condenser_water_pump_command` | `condenser_water_pump_command` | **`fraction` -> `boolean`** |
| `cw_return_t` | `condenser_water_return_temperature` | `return_condenser_water_temperature` | `DEG_C` |
| `cw_supply_t` | `condenser_water_supply_temperature` | `supply_condenser_water_temperature` | `DEG_C` |
| `damper_cmd` | `damper_command` | `damper_position_command` | **`fraction` -> `PERCENT` (x100)** |
| `damper_pct` | `damper_position` | `damper_position` | **`fraction` -> `PERCENT` (x100)** |
| `duct_static` | `duct_static_pressure` | `discharge_air_static_pressure` | `PA` |
| `duct_static_sp` | `duct_static_pressure_setpoint` | `discharge_air_static_pressure_setpoint` | `PA` |
| `electric_kw` | `electric_power` | `electric_power` | `KiloW` |
| `electric_kwh` | `electric_energy` | `electric_energy` | `KiloW-HR` |
| `fan_cmd` | `supply_fan_command` | `supply_fan_command` | **`fraction` -> `boolean`** |
| `fan_status` | `supply_fan_run_status` | `supply_fan_operating_status` | `boolean` |
| `heating_coil_entering_temp` | `heating_coil_entering_temperature` | `heating_coil_inlet_air_temperature` | `DEG_C` |
| `heating_coil_leaving_temp` | `heating_coil_leaving_temperature` | `heating_coil_outlet_air_temperature` | `DEG_C` |
| `heating_sp` | `heating_temperature_setpoint` | `zone_heating_air_temperature_setpoint` | `DEG_C` |
| `htg_valve_pct` | `heating_valve_position` | `heating_valve_position_command` | **`fraction` -> `PERCENT` (x100)** |
| `hw_reset_request_sum` | `hot_water_reset_request_count` | `hot_water_reset_request_count` | `NUM` |
| `hw_return_t` | `hot_water_return_temperature` | `return_hot_water_temperature` | `DEG_C` |
| `hw_supply_t` | `hot_water_supply_temperature` | `supply_hot_water_temperature` | `DEG_C` |
| `kwh` | `utility_electric_energy` | `electric_energy` | `KiloW-HR` |
| `loop_enabled` | `control_loop_enabled` | `operating_mode_status` | `boolean` |
| `ma_h` | `mixed_air_relative_humidity` | `mixed_air_relative_humidity` | `PERCENT_RH` |
| `mat` | `mixed_air_temperature` | `mixed_air_temperature` | `DEG_C` |
| `min_flow_sp` | `minimum_airflow_setpoint` | `discharge_air_volume_flow_rate_minimum` | `L-PER-SEC` |
| `oa_damper_pct` | `outside_air_damper_position` | `outdoor_air_intake_damper_position_command` | **`fraction` -> `PERCENT` (x100)** |
| `oa_h` | `outside_air_relative_humidity` | `outdoor_air_intake_relative_humidity` | `PERCENT_RH` |
| `oa_t` | `outside_air_temperature` | `outdoor_air_intake_temperature` | `DEG_C` |
| `occ_mode` | `occupancy_mode` | `occupancy_status` | `boolean` |
| `preheat_leave_t` | `preheat_leaving_air_temperature` | `preheat_heating_coil_outlet_air_temperature` | `DEG_C` |
| `pump_status` | `pump_run_status` | `pump_operating_status` | `boolean` |
| `ra_h` | `return_air_relative_humidity` | `return_air_relative_humidity` | `PERCENT_RH` |
| `rat` | `return_air_temperature` | `return_air_temperature` | `DEG_C` |
| `reheat_valve_pct` | `reheat_valve_position` | `terminal_unit_heating_valve_position_command` | **`fraction` -> `PERCENT` (x100)** |
| `return_fan` | `return_fan_command` | `return_fan_command` | **`fraction` -> `boolean`** |
| `run_proof` | `equipment_run_proof` | `operating_status` | `boolean` |
| `sa_h` | `discharge_air_relative_humidity` | `discharge_air_relative_humidity` | `PERCENT_RH` |
| `sat` | `discharge_air_temperature` | `discharge_air_temperature` | `DEG_C` |
| `sat_sp` | `discharge_air_temperature_setpoint` | `discharge_air_temperature_setpoint` | `DEG_C` |
| `static_reset_request` | `duct_static_pressure_reset_request_count` | `discharge_air_static_pressure_reset_request_count` | `NUM` |
| `tower_fan_cmd` | `cooling_tower_fan_command` | `cooling_tower_fan_command` | **`fraction` -> `boolean`** |
| `vav_discharge_t` | `terminal_unit_discharge_air_temperature` | `terminal_unit_discharge_air_temperature` | `DEG_C` |
| `vav_inlet_t` | `terminal_unit_inlet_air_temperature` | `terminal_unit_inlet_air_temperature` | `DEG_C` |
| `vav_total_flow` | `terminal_units_total_airflow` | `terminal_unit_discharge_air_total_volume_flow_rate` | `L-PER-SEC` |
| `web_oa_dp` | `weather_service_outside_air_dewpoint_temperature` | `weather_service_air_dew_point_temperature` | `DEG_C` |
| `web_oa_h` | `weather_service_outside_air_relative_humidity` | `weather_service_air_relative_humidity` | `PERCENT_RH` |
| `web_oa_t` | `weather_service_outside_air_temperature` | `weather_service_air_temperature` | `DEG_C` |
| `web_wb_t` | `weather_service_outside_air_wetbulb_temperature` | `weather_service_air_wet_bulb_temperature` | `DEG_C` |
| `zone_air_temp_sp` | `zone_air_temperature_setpoint` | `zone_air_temperature_setpoint` | `DEG_C` |
| `zone_airflow_sp` | `zone_airflow_setpoint` | `discharge_air_volume_flow_rate_setpoint` | `L-PER-SEC` |
| `zone_co2` | `zone_air_co2_concentration` | `zone_air_co2` | `PPM` |
| `zone_flow` | `zone_airflow` | `discharge_air_volume_flow_rate` | `L-PER-SEC` |
| `zone_rh` | `zone_air_relative_humidity` | `zone_air_relative_humidity` | `PERCENT_RH` |
| `zone_t` | `zone_air_temperature` | `zone_air_temperature` | `DEG_C` |

</details>

#1807 `InputName` rows that change: `outside_air_temperature` -> `outdoor_air_intake_temperature`,
`supply_fan_run_status` -> `supply_fan_operating_status`, `outside_air_damper_position` ->
`outdoor_air_intake_damper_position_command`, `cooling_valve_position` -> `cooling_valve_position_command`,
`heating_valve_position` -> `heating_valve_position_command`, `chilled_water_supply_temperature` ->
`supply_chilled_water_temperature`, `hot_water_supply_temperature` -> `supply_hot_water_temperature`,
`duct_static_pressure` -> `discharge_air_static_pressure`. The other six are unchanged.

## Unit changes

| Change | Inputs | Action |
|---|---|---|
| `fraction` -> `PERCENT` (x100) | `clg_valve_pct`, `htg_valve_pct`, `oa_damper_pct`, `reheat_valve_pct`, `damper_cmd`, `damper_pct` | ingest x100 from 0-1 sources; rules compare in 0-100 |
| `fraction` -> `boolean` | `fan_cmd`, `return_fan`, `chiller_cmd`, `chw_pump_cmd`, `cw_pump_cmd`, `tower_fan_cmd` | start/stop commands are `Binary-OnOff`; a speed belongs to `supply_fan_speed_command` (`PERCENT`) |
| scale tokens -> QUDT | all | `si:degC` -> `DEG_C`, `si:Pa` -> `PA`, `si:L/s` -> `L-PER-SEC`, `si:kW` -> `KiloW`, `si:kWh` -> `KiloW-HR`, `si:A` -> `A`, `si:ppm` -> `PPM`, `si:count` -> `NUM`, `percent_rh` -> `PERCENT_RH`, `text` -> `boolean` for occupancy |
| threshold units -> QUDT | `tuning_catalog.json` | `frac` -> `PERCENT`, `pct`/`%` -> `PERCENT`, `degC` differences and `degC_delta` -> `K`, `degC_delta_per_h` -> `K-PER-HR`, `L_per_s` -> `L-PER-SEC`, `min` -> `MIN`, `h` -> `HR` |

The 74 `kind: fraction` parameters below change to percent: multiply `default`, `min`, `max` and `step` by 100 and
update the label. Where a parameter only gates a start/stop command (`fan_on_min` and similar) and the input becomes
boolean, replace the threshold with the boolean test and retire the parameter through `legacy_parameters`.

<details><summary>42 rules, 74 fraction parameters</summary>

- [ ] `AHU-SIMUL` (`ahu_simul.sql`): `valve_open_pct`
- [ ] `CHW-2` (`chw2_dp_low.sql`): `pump_hi`
- [ ] `CHW-4` (`chw4_flow_high.sql`): `pump_hi`
- [ ] `CHW-NOLOAD-1` (`chw_noload_1.sql`): `load_sat_hi`
- [ ] `COIL-PERF` (`coil_perf.sql`): `valve_open`, `valve_shut`
- [ ] `CW-APR-1` (`cw_apr_1.sql`): `tower_fan_hi`
- [ ] `CW-FAN-1` (`cw_fan_1.sql`): `tower_fan_hi`
- [ ] `ECON-1` (`econ1_stuck_closed.sql`): `econ1_damper_max`
- [ ] `ECON-2` (`economizer_fault.sql`): `econ2_damper`
- [ ] `ECON-3` (`econ3_mech_without_econ.sql`): `clg_open_min`, `econ3_damper_hi`
- [ ] `ECON-5` (`econ5_preheat_over.sql`): `htg_open_min`
- [ ] `ECON-6` (`econ6_econ_freezing.sql`): `econ6_damper_max`
- [ ] `ECON-7` (`econ7_ok_not_economizing.sql`): `clg_open_min`, `econ7_damper_min`
- [ ] `FC1` (`fc1_duct_static_low.sql`): `eps_vfd_spd`, `fan_on_min`
- [ ] `FC10` (`fc10_mat_oa_clg.sql`): `clg_on_min`, `econ_full_open`, `fan_on_min`
- [ ] `FC11` (`fc11_oa_sat_sp_clg.sql`): `clg_on_min`, `econ_full_open`, `fan_on_min`
- [ ] `FC12` (`fc12_sat_mat_clg.sql`): `clg_on_min`, `econ_full_open`, `econ_min_pos`, `fan_on_min`
- [ ] `FC13-SAT-HIGH` (`sat_high_fault.sql`): `clg_full_min`, `econ_full_open`, `econ_min_pos`, `fan_on_min`, `oa_damper_econ_low`
- [ ] `FC14` (`fc14_chw_coil_dt_inactive.sql`): `clg_inactive_max`, `clg_on_min`, `econ_min_pos`, `fan_on_min`, `htg_on_min`
- [ ] `FC15` (`fc15_hw_coil_dt_inactive.sql`): `clg_inactive_max`, `clg_on_min`, `econ_full_open`, `econ_min_pos`, `fan_on_min`, `htg_on_min`
- [ ] `FC2` (`fc2_mat_low.sql`): `fan_on_min`
- [ ] `FC3` (`fc3_mat_high.sql`): `fan_on_min`
- [ ] `FC4` (`fc4_os_hunting.sql`): `fan_on_min`
- [ ] `FC5` (`fc5_sat_cold_heating.sql`): `fan_on_min`, `htg_on_min`
- [ ] `FC6` (`fc6_oa_frac_mismatch.sql`): `eps_airflow`, `fan_on_min`
- [ ] `FC7` (`fc7_sat_low_heating.sql`): `fan_on_min`, `htg_full_min`
- [ ] `FC8` (`fc8_sat_mat_econ.sql`): `clg_inactive_max`, `econ_min_pos`, `fan_on_min`
- [ ] `FC9` (`fc9_oa_sat_sp_econ.sql`): `clg_inactive_max`, `econ_min_pos`, `fan_on_min`
- [ ] `FCU-CLG-COIL` (`fcu_clg_coil.sql`): `valve_open`
- [ ] `FCU-CO2-DAMPER` (`fcu_co2_damper.sql`): `damper_low`
- [ ] `FCU-DAMPER-POS` (`fcu_damper_pos.sql`): `command_min`, `position_error`
- [ ] `FCU-HTG-COIL` (`fcu_htg_coil.sql`): `valve_open`
- [ ] `FCU-MODE-CYCLE` (`fcu_mode_cycle.sql`): `mode_valve_min`
- [ ] `FCU-SENSOR-NULL` (`fcu_sensor_null.sql`): `null_fraction` (scale the comparison with the threshold; see below)
- [ ] `OA-1` (`oa1_low_oa_frac.sql`): `min_oa_frac`
- [ ] `RESET-1` (`reset1_sat_oa_reset.sql`): `reset_slope`
- [ ] `SCHED-247` (`sched247_always_on.sql`): `always_on_pct`
- [ ] `VAV-3` (`vav3_excessive_reheat.sql`): `reheat_pct`
- [ ] `VAV-4` (`vav4_damper_full_open.sql`): `full_open_pct`
- [ ] `VAV-5` (`vav5_airflow_bias.sql`): `damper_closed_max`
- [ ] `VAV-6` (`vav6_reheat_free_cool.sql`): `reheat_pct`
- [ ] `VAV-REHEAT` (`vav_reheat.sql`): `reheat_cmd`

</details>

These 63 rules read a fraction-scaled input. Check each SQL file under `sql/fdd/postgres/` for hard-coded 0-1
constants (for example `FAN-RUNTIME-HOURS` tests `fan_cmd > 0.05`) and convert them:

`AHU-DUCTHI` (`fan_cmd`); `AHU-SATDEV` (`fan_cmd`); `AHU-SIMUL` (`clg_valve_pct`, `fan_cmd`, `htg_valve_pct`); `CHW-1` (`chw_pump_cmd`); `CHW-2` (`chw_pump_cmd`); `CHW-3` (`chw_pump_cmd`); `CHW-4` (`chw_pump_cmd`); `CHW-NOLOAD-1` (`chiller_cmd`, `chw_pump_cmd`); `CMD-1` (`fan_cmd`); `COIL-PERF` (`clg_valve_pct`, `fan_cmd`, `htg_valve_pct`, `reheat_valve_pct`); `CW-APR-1` (`chw_pump_cmd`, `tower_fan_cmd`); `CW-FAN-1` (`chw_pump_cmd`, `tower_fan_cmd`); `CW-OPT-1` (`chw_pump_cmd`); `DMP-1` (`fan_cmd`, `oa_damper_pct`); `ECON-1` (`fan_cmd`, `oa_damper_pct`); `ECON-2` (`fan_cmd`, `oa_damper_pct`); `ECON-3` (`clg_valve_pct`, `fan_cmd`, `oa_damper_pct`); `ECON-4` (`fan_cmd`); `ECON-5` (`fan_cmd`, `htg_valve_pct`); `ECON-6` (`fan_cmd`, `oa_damper_pct`); `ECON-7` (`clg_valve_pct`, `fan_cmd`, `oa_damper_pct`); `FAN-RUNTIME-HOURS` (`fan_cmd`); `FC1` (`fan_cmd`); `FC10` (`clg_valve_pct`, `fan_cmd`, `oa_damper_pct`); `FC11` (`clg_valve_pct`, `fan_cmd`, `oa_damper_pct`); `FC12` (`clg_valve_pct`, `fan_cmd`, `oa_damper_pct`); `FC13-SAT-HIGH` (`clg_valve_pct`, `fan_cmd`, `oa_damper_pct`); `FC14` (`clg_valve_pct`, `fan_cmd`, `oa_damper_pct`); `FC15` (`clg_valve_pct`, `fan_cmd`, `htg_valve_pct`); `FC2` (`fan_cmd`); `FC3` (`fan_cmd`); `FC4` (`clg_valve_pct`, `fan_cmd`, `oa_damper_pct`); `FC5` (`fan_cmd`, `htg_valve_pct`); `FC6` (`fan_cmd`); `FC7` (`fan_cmd`, `htg_valve_pct`); `FC8` (`clg_valve_pct`, `fan_cmd`, `oa_damper_pct`); `FC9` (`clg_valve_pct`, `fan_cmd`, `oa_damper_pct`); `FCU-CLG-COIL` (`clg_valve_pct`, `damper_cmd`, `damper_pct`, `fan_cmd`, `htg_valve_pct`); `FCU-CO2-DAMPER` (`clg_valve_pct`, `damper_cmd`, `damper_pct`, `fan_cmd`, `htg_valve_pct`); `FCU-DAMPER-POS` (`clg_valve_pct`, `damper_cmd`, `damper_pct`, `fan_cmd`, `htg_valve_pct`); `FCU-HTG-COIL` (`clg_valve_pct`, `damper_cmd`, `damper_pct`, `fan_cmd`, `htg_valve_pct`); `FCU-MODE-CYCLE` (`clg_valve_pct`, `htg_valve_pct`); `FCU-VALVE-PASS-CLG` (`clg_valve_pct`, `damper_cmd`, `damper_pct`, `fan_cmd`, `htg_valve_pct`); `FCU-VALVE-PASS-HTG` (`clg_valve_pct`, `damper_cmd`, `damper_pct`, `fan_cmd`, `htg_valve_pct`); `HP-1` (`fan_cmd`); `OA-1` (`fan_cmd`); `PID-HUNT-1` (`clg_valve_pct`, `damper_pct`, `fan_cmd`, `htg_valve_pct`, `oa_damper_pct`); `RESET-1` (`fan_cmd`); `SCHED-247` (`fan_cmd`); `SV-FLATLINE` (`chw_pump_cmd`, `fan_cmd`); `SV-RANGE` (`chw_pump_cmd`, `fan_cmd`); `SV-SPIKE` (`chw_pump_cmd`, `fan_cmd`); `TRIM-1` (`fan_cmd`); `TRIM-3` (`chw_pump_cmd`); `TRIM-4` (`chw_pump_cmd`); `VAV-3` (`fan_cmd`, `reheat_valve_pct`); `VAV-4` (`damper_pct`, `fan_cmd`); `VAV-5` (`damper_pct`, `fan_cmd`); `VAV-6` (`reheat_valve_pct`); `VAV-7` (`fan_cmd`); `VAV-AHU-LEAVE` (`fan_cmd`); `VAV-REHEAT` (`fan_cmd`, `reheat_valve_pct`); `VLV-1` (`clg_valve_pct`, `fan_cmd`); `FCU-SENSOR-NULL` (`null_fraction`)

**FCU-SENSOR-NULL.** `null_fraction` is one of the 74 parameters, so its default, min, max and step become percent
(default 90). `fcu_sensor_null.sql` compares `null_seconds / eligible_seconds` (a ratio in [0, 1]) with
`{{NULL_FRACTION}}` for both fault hours and `fault_pct`. The pandas twin in `open_fdd/rules/cookbook_catalog.py`
compares that same ratio with the threshold. Scale the comparison in the same change. Do not multiply the threshold
alone.

- SQL: both predicates use `100.0 * null_seconds / eligible_seconds >= {{NULL_FRACTION}}`. `fault_pct` already
  multiplies by 100 when it reports the percent; the predicate must use that percent ratio too.
- Pandas: compare `100.0 * null_fraction` with the percent threshold.
- The converted fixture is part of the pandas == SQL parity checks.

`occ_mode` is text today and `occupancy_status` is boolean. Map `occupied`, `true` and `1` to true, and `unoccupied`,
`false` and `0` to false. Any other string is not this role.

## Roles added for rules not yet on master

These three roles are not in the 75-key contract. Open rule work already uses the legacy keys. Keep those keys in
`legacy_keys` and bind the canonical role.

| Legacy key | Canonical role | Unit | Haystack markers |
|---|---|---|---|
| `boiler_status` | `boiler_operating_status` | boolean | `boiler`, `run`, `sensor` |
| `filter_dp` | `filter_air_pressure_delta` | `PA` | `filter`, `air`, `delta`, `pressure`, `sensor` |
| `fan_power` | `supply_fan_electric_power` | `KiloW` | `fan`, `elec`, `power`, `sensor` |

Damper, valve and fan-speed roles stay `PERCENT` (0-100). Flow stays `L-PER-SEC`. Power stays `KiloW` and energy
`KiloW-HR`.

**FC1 fan speed.** `FC1` compares `fan_cmd` with `eps_vfd_spd`. Bind it to `supply_fan_speed_command` (`PERCENT`,
Haystack `vfd`, `speed`, `cmd`). When that role is unbound, report the rule as not applicable rather than reading the
start/stop command. Set `rule_input: true` and `consumers.open-fdd: read` on that role in a minor roles release after `1.1.0`. Roles `1.1.0` leaves `rule_input` false, so the acceptance count stays 76.

## Haystack binding changes

Bindings in `nf-app/rules/role_overrides.json` (and so `fdd-catalog.json`) change for these 40 keys. The roles file is
the source; the catalog builder reads it. Also copy `equip_forbid`: `discharge_air_temperature` forbids parent
`airTerminalUnit` (that point binds `terminal_unit_discharge_air_temperature`); the supply-fan roles forbid parent
`coolingTower`, and `supply_fan_operating_status` also forbids parent `boiler`; `electric_power` forbids parent `chiller` and the point marker `fan`.

<details><summary>40 binding changes</summary>

| Key | Today: classes / markers | Canonical: classes / markers / forbid |
|---|---|---|
| `building_ahu_load_satisfied` | - / ahu, load, satisfied | - / ahu, load, satisfied, sensor / - |
| `building_zone_load_satisfied` | - / load, satisfied, zone | - / load, satisfied, sensor, zone / - |
| `chw_dp_sp` | - / chilled, delta, pressure, sp, water | - / chilled, delta, pressure, sp, water / max, min |
| `chw_flow` | chilled-water-delta-flow-sensor / chilled, flow, sensor, water | chilled-water-delta-flow-sensor / chilled, flow, sensor, water / max, min |
| `chw_reset_request_sum` | - / chilled, request, water | - / chilled, request, sensor, water / - |
| `chw_supply_sp` | - / chilled, leaving, sp, temp, water | - / chilled, leaving, sp, temp, water / max, min |
| `cooling_coil_entering_temp` | - / air, cool, entering, sensor, temp | - / air, cool, entering, sensor, temp / preheat, water |
| `cooling_coil_leaving_temp` | - / air, cool, leaving, sensor, temp | - / air, cool, leaving, sensor, temp / preheat, water |
| `cooling_sp` | zone-air-temp-occ-cooling-sp / air, cooling, sp, temp, zone | zone-air-temp-occ-cooling-sp / air, cooling, sp, temp, zone / heating, unocc, standby, effective, max, min |
| `damper_cmd` | damper-cmd / cmd, damper | damper-cmd, discharge-damper-cmd / cmd, damper / outside, return, exhaust, economizer, bypass |
| `damper_pct` | damper-cmd, damper-sensor / damper, sensor | damper-sensor, discharge-damper-sensor / damper, sensor / outside, return, exhaust, economizer, bypass |
| `duct_static_sp` | discharge-air-pressure-sp / air, discharge, pressure, sp | discharge-air-pressure-sp / air, discharge, pressure, sp / max, min |
| `electric_kw` | total-active-ac-elec-power-sensor / elec, power, sensor | total-active-ac-elec-power-sensor / elec, power, sensor / chiller, fan |
| `electric_kwh` | - / elec, energy, sensor | total-net-ac-elec-active-energy-sensor / elec, energy, sensor / - |
| `fan_cmd` | discharge-run-cmd, run-cmd / cmd, fan, run | discharge-run-cmd, run-cmd / cmd, fan, run / return, exhaust, pump |
| `fan_status` | discharge-run-sensor, run-sensor / fan, run, sensor | discharge-run-sensor, run-sensor / fan, run, sensor / return, exhaust, pump |
| `heating_coil_entering_temp` | - / air, entering, heat, sensor, temp | - / air, entering, heat, sensor, temp / preheat, water |
| `heating_coil_leaving_temp` | - / air, heat, leaving, sensor, temp | - / air, heat, leaving, sensor, temp / preheat, water |
| `heating_sp` | zone-air-temp-occ-heating-sp / air, heating, sp, temp, zone | zone-air-temp-occ-heating-sp / air, heating, sp, temp, zone / cooling, unocc, standby, effective, max, min |
| `htg_valve_pct` | discharge-hot-water-heat-valve-cmd, discharge-steam-heat-valve-cmd, hot-water-heat-valve-cmd / cmd, heat, valve | discharge-hot-water-heat-valve-cmd, discharge-steam-heat-valve-cmd, hot-water-heat-valve-cmd / cmd, heat, valve / reheat |
| `hw_reset_request_sum` | - / hot, request, water | - / hot, request, sensor, water / - |
| `kwh` | - / elec, energy, sensor | total-net-ac-elec-active-energy-sensor / elec, energy, sensor / - |
| `loop_enabled` | enable-cmd, enable-sensor / enable | enable-sensor / enable, sensor / cool, heat |
| `min_flow_sp` | - / air, flow, min, sp | - / air, flow, min, sp / max |
| `oa_damper_pct` | outside-damper-cmd, outside-damper-sensor / damper, outside | outside-damper-cmd / cmd, damper, outside / - |
| `oa_h` | outside-air-humidity-sensor / air, humidity, outside, sensor | outside-air-humidity-sensor / air, humidity, outside, sensor / weather |
| `oa_t` | outside-air-temp-sensor / air, outside, sensor, temp | outside-air-temp-sensor / air, outside, sensor, temp / weather |
| `occ_mode` | occupied-sensor / occupied | occupied-sensor / occupied / sp, cmd |
| `sat_sp` | discharge-air-temp-sp / air, discharge, sp, temp | discharge-air-temp-sp / air, discharge, sp, temp / max, min |
| `static_reset_request` | - / pressure, request | - / pressure, request, sensor / - |
| `tower_fan_cmd` | - / cmd, coolingTower, fan, run | - / cmd, fan, run / - |
| `vav_inlet_t` | inlet-air-temp-sensor / air, entering, sensor, temp | inlet-air-temp-sensor / air, inlet, sensor, temp / - |
| `vav_total_flow` | - / air, flow, sensor, total | - / air, flow, sensor, total / max, min |
| `web_oa_dp` | - / air, dewPoint, outside, weather | - / air, dewPoint, outside, sensor, weather / - |
| `web_oa_h` | - / air, humidity, outside, weather | - / air, humidity, outside, sensor, weather / - |
| `web_oa_t` | - / air, outside, temp, weather | - / air, outside, sensor, temp, weather / - |
| `web_wb_t` | - / air, outside, weather, wetBulb | - / air, outside, sensor, weather, wetBulb / - |
| `zone_air_temp_sp` | zone-air-temp-effective-sp / air, sp, temp, zone | zone-air-temp-effective-sp / air, sp, temp, zone / cooling, heating, occ, unocc, standby, max, min |
| `zone_airflow_sp` | air-flow-sp, discharge-air-flow-sp / air, flow, sp | air-flow-sp, discharge-air-flow-sp / air, flow, sp / max, min, total |
| `zone_flow` | air-flow-sensor, discharge-air-flow-sensor / air, flow, sensor | air-flow-sensor, discharge-air-flow-sensor / air, flow, sensor / max, min, total |

</details>

## Rules bundle (#1808) and UI contract (#1807)

- Bundle: ship `roles/openfdd-roles.json` and put its sha256 in the manifest. Delete `sql/fdd/input_names_223p.json`.
  Each manifest input carries the role name, unit and `haystack` block from the roles file, not a `role_map.json`
  label. `SCALE_UNIT` goes away.
- OpenAPI: generate `InputName` as an `enum` of the canonical `rule_input` roles from the roles file, and drop the
  hand-written table. `SiUnit` becomes the QUDT local names (role units plus the threshold units above). Add
  `enumeration` to `value_type` for site-defined mode commands. Occupancy is `boolean`. The UI shows
  `units[u].haystack` symbols.

## What can't be patched now

- **Site tags.** Open-FDD does not retag sites. Points tagged `ductStatic`, or lacking `sensor`/`cmd`, stop binding by
  markers; NF class matches still bind. `doctor` must list each unbound required input with the markers it needs.
- **Stored state.** `fdd.point.role` and `fdd.rule_config` (saved tunings) hold old keys and 0-1 values. Migrate them
  once in the upgrade path: rename roles through `legacy_keys` and multiply the saved fraction parameters by 100,
  guarded by the schema version. NF history holds raw point values and needs no change.
- **PyPI pandas API.** `open_fdd` accepts legacy column names through `legacy_keys`, with a `DeprecationWarning`, for
  the rest of 5.0.x. They are removed in 6.0.
- **4.x.** The frozen `v4.0.11-central` tag is not changed.

## Drift CI to add

1. Run `python3 roles/validate_roles.py` and `python3 -m unittest roles/test_validate_roles.py` on every PR.
2. `build_rule_catalog.py --check`, `build_sql_pack.py --check` and the bundle and OpenAPI builders fail when their
   output differs from what the roles file produces (names, units, bindings).
3. Add `tests/test_roles_contract.py`, which fails when:
   - a rule's required or optional role is not a canonical role
   - an input's unit differs from the role's `unit`
   - a position role binds a `cmd` class or marker
   - any `legacy_keys` or `aliases` value is used as a role identifier outside the legacy-key reader

## Acceptance criteria

- [ ] Every rule input in `fdd-catalog.json`, both SQL packs, the bundle manifest and the OpenAPI `InputName` enum is a
      canonical role. The four sets are equal, with 76 rule inputs in roles `1.1.0`.
- [ ] No `fraction` scale and no `frac` unit remain. All 74 parameters are in percent, and the converted fixtures pass
      the pandas == SQL parity tests, including `FCU-SENSOR-NULL` with its ratio scaled to percent in SQL and pandas.
- [ ] Every catalog binding (`classes`, `markers`, `forbid`, `equip_markers`) equals the roles file. A test shows that
      a `max` airflow point never binds `discharge_air_volume_flow_rate_setpoint`, and that a `damper-cmd` point never
      binds `damper_position`.
- [ ] `FC1` reads `supply_fan_speed_command`. Without it, `FC1` reports not applicable. The role's `rule_input` flag stays false in roles `1.1.0` and turns on in the next minor roles release, so this step does not add a 77th rule input to `1.1.0`.
- [ ] The upgrade migrates `fdd.point.role` and saved fraction tunings exactly once (a test runs it twice).
- [ ] The bundle ships the roles file with its sha256. `input_names_223p.json` is gone.
- [ ] `LICENSE` is the full MIT text below. `pyproject.toml` still declares MIT.
- [ ] The drift CI above runs and passes, along with every command in `AGENTS.md` "Tests to run before a PR".

## Checklist of files

- [ ] `sql/fdd/input_contract.json`, `input_contract.sql`, `role_map.json`, `role_scales.json`, `run_proof.json`,
      `tuning_catalog.json`, `runtime_defaults.json`, `registry.yaml`, `oracle_catalog.json`, `port_manifest.json`
- [ ] `sql/fdd/postgres/**/*.sql`: 79 files reference legacy keys
- [ ] `sql/fdd/schema/core.sql` plus its `open_fdd/data/core.sql` copy (role migration, tuning x100)
- [ ] `nf-app/rules/role_overrides.json`, `nf-app/rules/analytics/*.sql`
- [ ] Regenerate, never hand-edit: `nf-app/static/fdd-catalog.json`, `nf-app/rules/pack-postgres.json`,
      `nf-app/rules/pack-sqlite.json`, `open_fdd/data/fdd-catalog.json`, `docs/rules/*.md`
- [ ] `scripts/nf/build_rule_catalog.py`, `build_sql_pack.py`, `docs_units.py`, `gen_cookbook.py`,
      `build_sql_analytics_fixtures.py`; `scripts/build_rules_bundle.py` (#1808)
- [ ] `openapi/open-fdd-ui-api.yaml` (#1807)
- [ ] `nf-app/hooks/fdd.js`, `hooks/analytics.js`, `hooks/lib/engines.js`, `hooks/lib/sql-analytics.js`
- [ ] `nf-app/static/`: `rcx.js`, `rcx-overview.js`, `rcx-presets.js`, `fdd-plots.js`, `plot-spec.js`,
      `plot-spec-data.js`, `energy.js`, `occupancy.js`; `nf-app/rcx-parity.json`; `nf-app/dev/mock-nf.mjs`;
      `lite/static/model.js`
- [ ] `sql/analytics/*.sql` and the `open_fdd/data/*.sql` copies
- [ ] `open_fdd/data/`: `role_map.json`, `role_scales.json`, `parity_contract.json`,
      `parity_known_differences.json`, `rcx_presets.json`, `units.json`
- [ ] `open_fdd/`: `analytics/` (`role_map.py`, `core.py`, `charts.py`, `rcx_plots.py`, `point_stats.py`,
      `load_satisfaction.py`, `occupancy.py`, `sql_economizer.py`, `sql_runtime.py`, `topology_enrich.py`,
      `vav_health.py`, `weather_resolver.py`, `anomaly/activity.py`), `rules/` (`runner.py`, `summary.py`,
      `cookbook_catalog.py`, `custom_boilerplate.py`, `sensor_rate_profiles.py`), `parity/` (`dataset.py`,
      `imperial.py`), `ml/` (`detectors.py`, `folder.py`, `review_demo.py`), `plot_spec.py`
- [ ] Tests and fixtures: `tests/parity/`, `tests/fixtures/`, `tests/test_*.py`, `nf-app/tests/`,
      `nf-app/timescale/test/`
- [ ] `LICENSE`

## LICENSE

Replace `LICENSE` with:

```text
MIT License

Copyright (c) 2026 Open-FDD contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
