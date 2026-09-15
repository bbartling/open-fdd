---
title: SQL rules → Haystack map
parent: Haystack Modeling
nav_order: 7
permalink: /modeling/sql-rules-haystack-map.html
---

# SQL FDD rules → Haystack / data-model roles

Every production **DataFusion SQL** rule in [`sql_rules/registry.yaml`](https://github.com/bbartling/open-fdd/blob/master/sql_rules/registry.yaml) and the **Haystack point names** (or package map keys) that ingest into the SQL roles those rules need.

Ingest maps Haystack tags → SQL roles via `haystack_point_to_role` in [`crates/fdd_core/src/columns.rs`](https://github.com/bbartling/open-fdd/blob/master/crates/fdd_core/src/columns.rs). Blank / missing Haystack tags in a package = empty Overview / FDD / RCx — not a broken engine. See [Package authoring](../agent/PACKAGE_AUTHORING.md) and [Rule readiness](rule-readiness.html).

**Registry count:** **68** SQL rules (live). Re-generate this page when the registry changes.

| Rule id | Required Haystack → SQL role | Optional Haystack → SQL role |
|---------|------------------------------|------------------------------|
| `FAN-RUNTIME-HOURS` | `fan-cmd` → `fan_cmd` | — |
| `VAV-1` | `zone-air-temp` → `zone_t` | `occupied` → `occ_mode` |
| `VAV-2` | `zone-air-temp` → `zone_t`, `occupied` → `occ_mode` | — |
| `AVG-ZONE-TEMP` | `zone-air-temp` → `zone_t` | — |
| `ZONE-COMFORT-PCT` | `zone-air-temp` → `zone_t` | — |
| `FAULT-ELAPSED-HOURS` | `zone-air-temp` → `zone_t` | — |
| `OAT-METEO` | `outside-air-temp` → `oa_t` | `web-outside-air-temp` → `web_oa_t` |
| `FC13-SAT-HIGH` | `discharge-air-temp` → `sat`, `discharge-air-temp-sp` → `sat_sp`, `cooling-valve` → `clg_valve_pct`, `outside-air-damper` → `oa_damper_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `ECON-2` | `outside-air-temp` → `oa_t`, `outside-air-damper` → `oa_damper_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC1` | `duct-static-pressure` → `duct_static`, `duct-static-pressure-sp` → `duct_static_sp`, `fan-cmd` → `fan_cmd` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC2` | `mixed-air-temp` → `mat`, `outside-air-temp` → `oa_t`, `return-air-temp` → `rat`, `fan-cmd` → `fan_cmd` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC3` | `mixed-air-temp` → `mat`, `outside-air-temp` → `oa_t`, `return-air-temp` → `rat`, `fan-cmd` → `fan_cmd` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC7` | `discharge-air-temp` → `sat`, `discharge-air-temp-sp` → `sat_sp`, `heating-valve` → `htg_valve_pct` | `fan-cmd` → `fan_cmd`, `fan-status` → `fan_status` |
| `FC8` | `discharge-air-temp` → `sat`, `mixed-air-temp` → `mat`, `outside-air-damper` → `oa_damper_pct`, `cooling-valve` → `clg_valve_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC9` | `outside-air-temp` → `oa_t`, `discharge-air-temp-sp` → `sat_sp`, `outside-air-damper` → `oa_damper_pct`, `cooling-valve` → `clg_valve_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC10` | `mixed-air-temp` → `mat`, `outside-air-temp` → `oa_t`, `outside-air-damper` → `oa_damper_pct`, `cooling-valve` → `clg_valve_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC11` | `outside-air-temp` → `oa_t`, `discharge-air-temp-sp` → `sat_sp`, `outside-air-damper` → `oa_damper_pct`, `cooling-valve` → `clg_valve_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC12` | `discharge-air-temp` → `sat`, `mixed-air-temp` → `mat`, `outside-air-damper` → `oa_damper_pct`, `cooling-valve` → `clg_valve_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `ECON-1` | `fan-cmd` → `fan_cmd`, `outside-air-damper` → `oa_damper_pct`, `outside-air-temp` → `oa_t` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `ECON-4` | `mixed-air-temp` → `mat`, `return-air-temp` → `rat`, `outside-air-temp` → `oa_t`, `fan-cmd` → `fan_cmd` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `SV-RANGE` | — | `outside-air-temp` → `oa_t`, `mixed-air-temp` → `mat`, `zone-air-temp` → `zone_t`, `return-air-temp` → `rat`, `discharge-air-temp` → `sat`, `chilled-water-supply-temp` → `chw_supply_t`, `chilled-water-return-temp` → `chw_return_t`, `hot-water-supply-temp` → `hw_supply_t`, `hot-water-return-temp` → `hw_return_t`, `outside-air-humidity` → `oa_h`, `duct-static-pressure` → `duct_static`, `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd`, `pump-status` → `pump_status`, `chw-pump-cmd` → `chw_pump_cmd`, `chiller-status` → `chiller_status`, `elec-energy` → `kwh`, `elec-power` → `electric_kw`, `elec-energy` → `electric_kwh` |
| `SV-FLATLINE` | — | `outside-air-temp` → `oa_t`, `mixed-air-temp` → `mat`, `zone-air-temp` → `zone_t`, `return-air-temp` → `rat`, `discharge-air-temp` → `sat`, `chilled-water-supply-temp` → `chw_supply_t`, `chilled-water-return-temp` → `chw_return_t`, `hot-water-supply-temp` → `hw_supply_t`, `hot-water-return-temp` → `hw_return_t`, `outside-air-humidity` → `oa_h`, `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd`, `pump-status` → `pump_status`, `chw-pump-cmd` → `chw_pump_cmd`, `chiller-status` → `chiller_status` |
| `SV-SPIKE` | — | `outside-air-temp` → `oa_t`, `mixed-air-temp` → `mat`, `zone-air-temp` → `zone_t`, `return-air-temp` → `rat`, `discharge-air-temp` → `sat`, `chilled-water-supply-temp` → `chw_supply_t`, `chilled-water-return-temp` → `chw_return_t`, `hot-water-supply-temp` → `hw_supply_t`, `hot-water-return-temp` → `hw_return_t`, `outside-air-humidity` → `oa_h`, `duct-static-pressure` → `duct_static`, `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd`, `pump-status` → `pump_status`, `chw-pump-cmd` → `chw_pump_cmd`, `chiller-status` → `chiller_status` |
| `SV-STALE` | — | `outside-air-temp` → `oa_t`, `mixed-air-temp` → `mat`, `zone-air-temp` → `zone_t`, `return-air-temp` → `rat`, `discharge-air-temp` → `sat`, `chilled-water-supply-temp` → `chw_supply_t`, `chilled-water-return-temp` → `chw_return_t`, `hot-water-supply-temp` → `hw_supply_t`, `hot-water-return-temp` → `hw_return_t`, `outside-air-humidity` → `oa_h` |
| `SV-RATE` | — | `outside-air-temp` → `oa_t`, `mixed-air-temp` → `mat`, `zone-air-temp` → `zone_t`, `return-air-temp` → `rat`, `discharge-air-temp` → `sat` |
| `PID-HUNT-1` | — | `outside-air-damper` → `oa_damper_pct`, `cooling-valve` → `clg_valve_pct`, `heating-valve` → `htg_valve_pct`, `damper` → `damper_pct`, `loop-enabled` → `loop_enabled`, `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC4` | `outside-air-damper` → `oa_damper_pct`, `cooling-valve` → `clg_valve_pct`, `fan-cmd` → `fan_cmd` | `fan-status` → `fan_status` |
| `FC5` | `discharge-air-temp` → `sat`, `mixed-air-temp` → `mat`, `heating-valve` → `htg_valve_pct`, `fan-cmd` → `fan_cmd` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC6` | `mixed-air-temp` → `mat`, `return-air-temp` → `rat`, `outside-air-temp` → `oa_t`, `fan-cmd` → `fan_cmd`, `vav-total-airflow` → `vav_total_flow` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC14` | `cooling-valve` → `clg_valve_pct` | `cooling-coil-entering-temp` → `cooling_coil_entering_temp`, `cooling-coil-leaving-temp` → `cooling_coil_leaving_temp`, `mixed-air-temp` → `mat`, `discharge-air-temp` → `sat`, `outside-air-damper` → `oa_damper_pct`, `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `FC15` | — | `heating-coil-entering-temp` → `heating_coil_entering_temp`, `heating-coil-leaving-temp` → `heating_coil_leaving_temp`, `mixed-air-temp` → `mat`, `discharge-air-temp` → `sat`, `heating-valve` → `htg_valve_pct`, `cooling-valve` → `clg_valve_pct`, `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `AHU-SATDEV` | `discharge-air-temp` → `sat`, `discharge-air-temp-sp` → `sat_sp` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `AHU-DUCTHI` | `duct-static-pressure` → `duct_static`, `duct-static-pressure-sp` → `duct_static_sp`, `fan-cmd` → `fan_cmd` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `AHU-SIMUL` | `heating-valve` → `htg_valve_pct`, `cooling-valve` → `clg_valve_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `ECON-3` | `outside-air-damper` → `oa_damper_pct`, `cooling-valve` → `clg_valve_pct` | `web-outside-air-temp` → `web_oa_t`, `web-outside-air-dewpoint` → `web_oa_dp`, `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `ECON-5` | `preheat-leaving-temp` → `preheat_leave_t`, `discharge-air-temp-sp` → `sat_sp`, `outside-air-temp` → `oa_t`, `heating-valve` → `htg_valve_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `ECON-6` | `outside-air-damper` → `oa_damper_pct` | `web-outside-air-temp` → `web_oa_t`, `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `ECON-7` | `outside-air-damper` → `oa_damper_pct`, `cooling-valve` → `clg_valve_pct` | `web-outside-air-temp` → `web_oa_t`, `web-outside-air-dewpoint` → `web_oa_dp`, `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `MECH-OAT-1` | `web-outside-air-temp` → `web_oa_t` | `cooling-valve` → `clg_valve_pct`, `chiller-status` → `chiller_status` |
| `CMD-1` | `fan-cmd` → `fan_cmd`, `fan-status` → `fan_status` | — |
| `OA-1` | `mixed-air-temp` → `mat`, `return-air-temp` → `rat`, `outside-air-temp` → `oa_t`, `fan-cmd` → `fan_cmd` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `DMP-1` | `outside-air-damper` → `oa_damper_pct`, `outside-air-temp` → `oa_t`, `mixed-air-temp` → `mat` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `VLV-1` | `cooling-valve` → `clg_valve_pct`, `discharge-air-temp` → `sat`, `discharge-air-temp-sp` → `sat_sp`, `mixed-air-temp` → `mat` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `VAV-3` | `outside-air-temp` → `oa_t`, `reheat-valve` → `reheat_valve_pct`, `zone-airflow` → `zone_flow` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `VAV-4` | `damper` → `damper_pct`, `zone-airflow` → `zone_flow` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `VAV-5` | `zone-airflow` → `zone_flow`, `damper` → `damper_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `VAV-6` | `outside-air-temp` → `oa_t`, `reheat-valve` → `reheat_valve_pct` | `clg-available` → `clg_available` |
| `VAV-REHEAT` | `reheat-valve` → `reheat_valve_pct`, `vav-discharge-air-temp` → `vav_discharge_t`, `vav-inlet-air-temp` → `vav_inlet_t`, `zone-airflow` → `zone_flow` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `VAV-AHU-LEAVE` | `vav-discharge-air-temp` → `vav_discharge_t`, `ahu-discharge-air-temp` → `ahu_sat`, `zone-airflow` → `zone_flow` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `VAV-7` | `zone-airflow` → `zone_flow` | `min-flow-sp` → `min_flow_sp`, `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `RESET-1` | `discharge-air-temp-sp` → `sat_sp`, `outside-air-temp` → `oa_t` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `CHW-NOLOAD-1` | — | `chiller-status` → `chiller_status`, `chiller-cmd` → `chiller_cmd`, `chw-pump-status` → `chw_pump_status`, `chw-pump-cmd` → `chw_pump_cmd`, `building-zone-load-satisfied` → `building_zone_load_satisfied`, `building-ahu-load-satisfied` → `building_ahu_load_satisfied` |
| `CHW-1` | `chilled-water-supply-temp` → `chw_supply_t`, `chilled-water-return-temp` → `chw_return_t` | `chw-pump-cmd` → `chw_pump_cmd`, `pump-status` → `pump_status`, `chiller-status` → `chiller_status`, `chiller-current` → `chiller_current`, `chiller-amps` → `chiller_amps`, `chiller-power` → `chiller_power`, `chw-flow` → `chw_flow` |
| `CHW-2` | `chw-diff-pressure` → `chw_dp`, `chw-diff-pressure-sp` → `chw_dp_sp`, `chw-pump-cmd` → `chw_pump_cmd` | — |
| `CHW-3` | `chilled-water-supply-temp` → `chw_supply_t`, `chilled-water-supply-temp-sp` → `chw_supply_sp`, `chw-pump-cmd` → `chw_pump_cmd` | — |
| `CHW-4` | `chw-flow` → `chw_flow`, `chw-pump-cmd` → `chw_pump_cmd` | — |
| `CW-OPT-1` | `condenser-water-supply-temp` → `cw_supply_t`, `web-outside-air-wetbulb` → `web_wb_t` | `pump-status` → `pump_status`, `chiller-status` → `chiller_status`, `chw-flow` → `chw_flow`, `chw-pump-cmd` → `chw_pump_cmd` |
| `CW-APR-1` | `condenser-water-supply-temp` → `cw_supply_t`, `web-outside-air-wetbulb` → `web_wb_t`, `tower-fan-cmd` → `tower_fan_cmd` | `pump-status` → `pump_status`, `chiller-status` → `chiller_status`, `chw-flow` → `chw_flow`, `chw-pump-cmd` → `chw_pump_cmd` |
| `CW-FAN-1` | `condenser-water-supply-temp` → `cw_supply_t`, `web-outside-air-wetbulb` → `web_wb_t`, `tower-fan-cmd` → `tower_fan_cmd` | `pump-status` → `pump_status`, `chiller-status` → `chiller_status`, `chw-flow` → `chw_flow`, `chw-pump-cmd` → `chw_pump_cmd` |
| `HP-1` | `discharge-air-temp` → `sat`, `zone-air-temp` → `zone_t`, `fan-cmd` → `fan_cmd` | `compressor-status` → `compressor_status`, `fan-status` → `fan_status` |
| `WX-1` | `outside-air-temp` → `oa_t` | — |
| `TRIM-1` | `duct-static-pressure` → `duct_static` | `duct-static-pressure-sp` → `duct_static_sp`, `static-reset-request` → `static_reset_request`, `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` |
| `TRIM-3` | `hot-water-supply-temp` → `hw_supply_t` | `pump-status` → `pump_status`, `chiller-status` → `chiller_status`, `chw-flow` → `chw_flow`, `chw-pump-cmd` → `chw_pump_cmd` |
| `TRIM-4` | `chilled-water-supply-temp` → `chw_supply_t` | `pump-status` → `pump_status`, `chiller-status` → `chiller_status`, `chw-flow` → `chw_flow`, `chw-pump-cmd` → `chw_pump_cmd` |
| `SCHED-1` | `occupied` → `occ_mode`, `fan-status` → `fan_status` | `zone-air-temp` → `zone_t` |
| `SCHED-247` | — | `fan-status` → `fan_status`, `pump-status` → `pump_status`, `chiller-status` → `chiller_status`, `fan-cmd` → `fan_cmd` |
| `UTIL-MONTHLY` | — | `elec-energy` → `kwh`, `elec-power` → `electric_kw` |
| `UTIL-INTERVAL` | — | `elec-energy` → `kwh`, `elec-power` → `electric_kw` |

## Role ↔ Haystack quick reference

| SQL role | Preferred Haystack tag |
|----------|------------------------|
| `ahu_sat` | `ahu-discharge-air-temp` |
| `building_ahu_load_satisfied` | `building-ahu-load-satisfied` |
| `building_zone_load_satisfied` | `building-zone-load-satisfied` |
| `chiller_amps` | `chiller-amps` |
| `chiller_cmd` | `chiller-cmd` |
| `chiller_current` | `chiller-current` |
| `chiller_power` | `chiller-power` |
| `chiller_status` | `chiller-status` |
| `chw_dp` | `chw-diff-pressure` |
| `chw_dp_sp` | `chw-diff-pressure-sp` |
| `chw_flow` | `chw-flow` |
| `chw_pump_cmd` | `chw-pump-cmd` |
| `chw_pump_status` | `chw-pump-status` |
| `chw_return_t` | `chilled-water-return-temp` |
| `chw_supply_sp` | `chilled-water-supply-temp-sp` |
| `chw_supply_t` | `chilled-water-supply-temp` |
| `clg_valve_pct` | `cooling-valve` |
| `compressor_status` | `compressor-status` |
| `cooling_coil_entering_temp` | `cooling-coil-entering-temp` |
| `cooling_coil_leaving_temp` | `cooling-coil-leaving-temp` |
| `cw_pump_cmd` | `cw-pump-cmd` |
| `cw_return_t` | `condenser-water-return-temp` |
| `cw_supply_t` | `condenser-water-supply-temp` |
| `damper_pct` | `damper` |
| `duct_static` | `duct-static-pressure` |
| `duct_static_sp` | `duct-static-pressure-sp` |
| `elec_power` | `elec-power` |
| `electric_kw` | `elec-power` |
| `electric_kwh` | `elec-energy` |
| `fan_cmd` | `fan-cmd` |
| `fan_status` | `fan-status` |
| `heating_coil_entering_temp` | `heating-coil-entering-temp` |
| `heating_coil_leaving_temp` | `heating-coil-leaving-temp` |
| `htg_valve_pct` | `heating-valve` |
| `hw_pump_cmd` | `hw-pump-cmd` |
| `hw_pump_status` | `hw-pump-status` |
| `hw_return_t` | `hot-water-return-temp` |
| `hw_supply_t` | `hot-water-supply-temp` |
| `kwh` | `elec-energy` |
| `loop_enabled` | `loop-enabled` |
| `mat` | `mixed-air-temp` |
| `min_flow_sp` | `min-flow-sp` |
| `oa_damper_pct` | `outside-air-damper` |
| `oa_h` | `outside-air-humidity` |
| `oa_t` | `outside-air-temp` |
| `occ_mode` | `occupied` |
| `preheat_leave_t` | `preheat-leaving-temp` |
| `pump_status` | `pump-status` |
| `rat` | `return-air-temp` |
| `reheat_valve_pct` | `reheat-valve` |
| `return_fan` | `return-fan-cmd` |
| `sat` | `discharge-air-temp` |
| `sat_sp` | `discharge-air-temp-sp` |
| `static_reset_request` | `static-reset-request` |
| `tower_fan_cmd` | `tower-fan-cmd` |
| `vav_discharge_t` | `vav-discharge-air-temp` |
| `vav_inlet_t` | `vav-inlet-air-temp` |
| `vav_total_flow` | `vav-total-airflow` |
| `web_oa_dp` | `web-outside-air-dewpoint` |
| `web_oa_h` | `web-outside-air-humidity` |
| `web_oa_t` | `web-outside-air-temp` |
| `web_wb_t` | `web-outside-air-wetbulb` |
| `zone_flow` | `zone-airflow` |
| `zone_rh` | `zone-air-humidity` |
| `zone_t` | `zone-air-temp` |

## Related

- [Rule Cookbook]({{ site.baseurl }}/rules/cookbook/) — SQL + Pandas recipes
- [Role mapping parity](../migration/vibe19/ROLE_MAPPING_PARITY.md)
- [Assignments](assignments.html)

