---
title: P0 rule catalog (metadata)
parent: Cookbook reference
grand_parent: Rule Cookbook
nav_order: 10
nav_exclude: true
---

# P0 rule catalog — full metadata

Parameters, data, and thresholds use SI semantic kinds. Source-point units are engineer-declared and normalized once; display conversion is separate. This metadata catalog records rule intent; use [`sql/fdd/registry.yaml`](../../../sql/fdd/registry.yaml) as the current parameter contract. See [units](../../modeling/units.md).


Standards-first metadata for every **validated** cookbook rule (vibe19 catalog). Detection SQL/Pandas live in the [SQL](sql-cookbook.html) and [Pandas](pandas-cookbook.html) cookbooks.

{: .important }
All **thresholds are defaults** — site-adjustable. **confirmation_seconds** default **300** unless noted.

---

## Validated rules

| id | family | equipment | roles | confirmation_s | equation |
|----|--------|-----------|-------|----------------:|----------|
| `SV-RANGE` | `sensor` | ahu, vav, chiller, boiler, weather, zone, heatpump |  | 300 | Any modeled sensor reads outside its physical hard range (e.g. OAT −51–54°C, SAT −1–66°C, CHWS −1–27°C). |
| `SV-FLATLINE` | `sensor` | ahu, vav, chiller, boiler, weather, zone, heatpump |  | 300 | Sensor value unchanged (Δ ≤ tolerance) across the flatline window — stuck / frozen sensor. |
| `SV-SPIKE` | `sensor` | ahu, vav, chiller, boiler, weather, zone, heatpump |  | 300 | Sample-to-sample jump exceeds the physical spike limit for the sensor type. |
| `SV-STALE` | `sensor` | ahu, vav, chiller, boiler, weather, zone, heatpump |  | 300 | All modeled sensors unchanged over the stale window — data feed likely dropped. |
| `SV-RATE` | `sensor` | ahu, vav, chiller, boiler, weather, zone, heatpump |  | 600 | Implausible sustained rate-of-change for mapped sensors. Thresholds depend on quantity, location, and operating state… |
| `PID-HUNT-1` | `control` | ahu, vav, chiller, boiler, heatpump |  | 300 | Rolling 1h total variation of any 0–100% control output (dampers, valves, fan speeds, heat/cool cmds) with span ≥20%,… |
| `FC1` | `ahu` | ahu | duct-static-pressure, duct-static-pressure-sp, fan-cmd | 300 | Fan ≥ 87% AND duct static < static SP − 29.8608 Pa (0.12 in. w.c.) |
| `FC2` | `ahu` | ahu | mixed-air-temp, outside-air-temp, return-air-temp, fan-cmd | 600 | Fan on AND MAT + mix_tol < min(RAT − mix_tol, OAT − mix_tol) (≡ MAT < min(RAT, OAT) − 2·mix_tol; default mix_tol = 1.… |
| `FC3` | `ahu` | ahu | mixed-air-temp, outside-air-temp, return-air-temp, fan-cmd | 600 | Fan on AND MAT − mix_tol > max(RAT + mix_tol, OAT + mix_tol) (≡ MAT > max(RAT, OAT) + 2·mix_tol; default mix_tol = 1.… |
| `FC4` | `ahu` | ahu | outside-air-damper, cooling-valve, fan-cmd | 3600 | More than 5 operating-mode entry transitions in any hour (heating/econ/mech modes). |
| `FC5` | `ahu` | ahu | discharge-air-temp, mixed-air-temp, fan-cmd, heating-valve | 600 | Fan on AND heating > 1% AND SAT + mix_tol ≤ MAT − mix_tol + 0.31Δ°C (default mix_tol = 0.64°C). |
| `FC6` | `ahu` | ahu | mixed-air-temp, outside-air-temp, return-air-temp, vav-total-airflow | 600 | \\|RAT−OAT\\| ≥ 2.78Δ°C AND \\|estimated OA% − design min OA%\\| > 15% in heating/mech-only modes. |
| `FC7` | `ahu` | ahu | discharge-air-temp, discharge-air-temp-sp, fan-cmd, heating-valve | 600 | Fan on AND heating > 90% AND SAT < SAT SP − 0.638889°C (temperature difference). |
| `FC8` | `ahu` | ahu | discharge-air-temp, mixed-air-temp, outside-air-damper, cooling-valve | 600 | Economizer open, CHW < 10%, \\|SAT − 0.31Δ°C − MAT\\| > √(supply_tol²+mix_tol²). |
| `FC9` | `ahu` | ahu | outside-air-temp, discharge-air-temp-sp, outside-air-damper, cooling-valve | 600 | Economizer open, CHW < 10%, OAT − mix_tol > SAT SP − 0.31Δ°C + mix_tol. |
| `FC10` | `ahu` | ahu | mixed-air-temp, outside-air-temp, outside-air-damper, cooling-valve | 600 | CHW > 1%, economizer > 90%, \\|MAT − OAT\\| > √(mix_tol²+mix_tol²). |
| `FC11` | `ahu` | ahu | outside-air-temp, discharge-air-temp-sp, outside-air-damper, cooling-valve | 600 | CHW > 1%, economizer > 90%, OAT + mix_tol < SAT SP − 0.31Δ°C − mix_tol. |
| `FC12` | `ahu` | ahu | discharge-air-temp, mixed-air-temp, outside-air-damper, cooling-valve | 600 | CHW > 1%, SAT − supply_tol − 0.31Δ°C > MAT + mix_tol at min or full economizer. |
| `FC13` | `ahu` | ahu | discharge-air-temp, discharge-air-temp-sp, outside-air-damper, cooling-valve | 600 | CHW > 1%, SAT > SAT SP + 0.638889°C (temperature difference) at min or full economizer. |
| `FC14` | `ahu` | ahu | cooling-coil-entering-temp, cooling-coil-leaving-temp, outside-air-damper, cooling-valve | 600 | Cooling coil ΔT ≥ √(mix_tol²+mix_tol²)+0.31Δ°C while coil should be inactive. |
| `FC15` | `ahu` | ahu | heating-coil-entering-temp, heating-coil-leaving-temp, outside-air-damper, cooling-valve | 600 | Heating coil ΔT ≥ √(mix_tol²+mix_tol²)+0.31Δ°C while coil should be inactive. |
| `AHU-SATDEV` | `ahu` | ahu | discharge-air-temp, discharge-air-temp-sp | 600 | \\|SAT − SAT SP\\| > 2.78Δ°C. |
| `AHU-DUCTHI` | `ahu` | ahu | duct-static-pressure, duct-static-pressure-sp | 300 | Duct static > static SP + margin. Evaluates when fan is proven on OR duct static itself exceeds pressure_on_min (catc… |
| `AHU-SIMUL` | `ahu` | ahu | heating-valve, cooling-valve | 300 | Heating valve > 10% AND cooling valve > 10% at once. |
| `OAT-METEO` | `ahu` | ahu | outside-air-temp, web-outside-air-temp | 900 | BAS OAT sensor differs from Open-Meteo dry bulb by more than 2.78Δ°C. |
| `ECON-1` | `ahu` | ahu | fan-cmd, outside-air-damper, outside-air-temp | 600 | Fan on, OA damper < 5%, OAT > 12.78°C (should be economizing). |
| `ECON-2` | `ahu` | ahu | outside-air-temp, outside-air-damper | 300 | OAT > 17.22°C AND OA damper > 42% (should be at minimum). |
| `ECON-3` | `ahu` | ahu | outside-air-damper, cooling-valve | 300 | Web free-cooling opportunity: 15.56°C ≤ dry-bulb < 22.22°C AND dewpoint < 15.56°C (dewpoint from web sensor or calculated from… |
| `ECON-4` | `ahu` | ahu | mixed-air-temp, return-air-temp, outside-air-temp, fan-cmd | 600 | Fan on, \\|RAT−OAT\\| > 1.22Δ°C, estimated OA fraction < 21%. |
| `ECON-5` | `ahu` | ahu | preheat-leaving-temp, discharge-air-temp-sp, outside-air-temp, heating-valve | 600 | Preheat leaving air > 1.22Δ°C above target while preheat active. |
| `ECON-6` | `ahu` | ahu | outside-air-damper | 600 | Web dry-bulb < -3.89°C AND OA damper above winter min-OA ceiling (default 25%). AHU should be at minimum OA in cold weat… |
| `ECON-7` | `ahu` | ahu | outside-air-damper | 600 | Economizer-OK web weather: dew point < 15.56°C AND dry-bulb < 22.22°C (above a 1.67°C freeze-guard floor; dewpoint from web s… |
| `MECH-OAT-1` | `ahu` | ahu, chiller, heatpump |  | 600 | Proven DX/chiller mechanical cooling while web dry-bulb < 15.56°C. Uses compressor/chiller/pump/amps/power proof — not A… |
| `CHW-NOLOAD-1` | `plant` | chiller |  | 1800 | Chiller/plant proven running while building load is satisfied: all mapped zones inside comfort band OR all mapped AHU… |
| `VAV-1` | `vav` | vav, zone_other, heatpump, baseboard | zone-air-temp | 900 | Zone temp outside 21.11–23.89°C during occupied hours when occupancy is set (`require_occupied`, default on). Unoccupied setback is VAV-2. |
| `VAV-2` | `vav` | vav, zone | zone-air-temp, occupied | 900 | Unoccupied AND zone temp > setback_hi (default 20°C). |
| `VAV-3` | `vav` | vav | outside-air-temp, reheat-valve | 300 | Air flowing AND OAT > 25.56°C AND reheat valve > 52%. |
| `VAV-4` | `vav` | vav | damper | 900 | Air flowing AND damper > 97.5% sustained across the window. |
| `VAV-5` | `vav` | vav | zone-airflow, damper | 900 | Airflow > 50 L/s while damper < 10% (implausible flow). |
| `VAV-6` | `vav` | vav | outside-air-temp, reheat-valve | 900 | OAT < 18.33°C AND reheat valve > 25%. |
| `VAV-REHEAT` | `vav` | vav | reheat-valve, vav-discharge-air-temp, vav-inlet-air-temp | 900 | Air flowing AND reheat valve > 30% AND box discharge temp rises < 1.67Δ°C above duct inlet (air from AHU) — stuck or fail… |
| `VAV-AHU-LEAVE` | `vav` | vav | vav-discharge-air-temp, ahu-discharge-air-temp | 900 | Air flowing AND \\|VAV discharge − parent AHU SAT\\| > band. Needs package topology (vav_to_ahu) so ahu_sat is enrich… |
| `VAV-7` | `vav` | vav | zone-airflow | 900 | Flow below min SP (when mapped), OR airflow stays flat (low rolling std) at a high mean while air is on (mins too hig… |
| `FCU-SENSOR-NULL` | `fcu` | zone_other, general, ahu | zone-air-temp-sp | 0 | Own zone setpoint present and zone temperature null for at least 90% of the window. |
| `FCU-HTG-COIL` | `fcu` | zone_other, general, ahu | discharge-air-temp, zone-air-temp, heating-valve | 900 | Fan on, heating valve ≥ 80%, SAT − zone < 3Δ°C. |
| `FCU-CLG-COIL` | `fcu` | zone_other, general, ahu | discharge-air-temp, zone-air-temp, cooling-valve, heating-valve | 900 | Fan on, cooling ≥ 80%, heating shut, SAT not below zone. |
| `FCU-VALVE-PASS-HTG` | `fcu` | zone_other, general, ahu | discharge-air-temp, zone-air-temp, heating-valve, cooling-valve | 900 | Fan on, both valves shut, SAT − zone > 3Δ°C. |
| `FCU-VALVE-PASS-CLG` | `fcu` | zone_other, general, ahu | discharge-air-temp, zone-air-temp, heating-valve, cooling-valve | 900 | Fan on, both valves shut, zone − SAT > 3Δ°C. |
| `FCU-DAMPER-POS` | `fcu` | zone_other, general, ahu | damper-cmd, damper | 900 | Fan on, damper command ≥ 15%, feedback more than 15 points below command. |
| `FCU-CO2-DAMPER` | `fcu` | zone_other, general, ahu | zone-co2, damper-cmd | 900 | Fan on, valid CO₂ > 1000 ppm, damper command < 10%. |
| `FCU-DEADBAND` | `fcu` | zone_other, general, ahu | cooling-sp, heating-sp | 0 | Pass-through cooling SP − heating SP < 1°C. |
| `FCU-MODE-CYCLE` | `fcu` | zone_other, general, ahu | heating-valve, cooling-valve | 0 | At least four heat/cool valve mode changes in the window. |
| `CHW-1` | `plant` | chiller | chilled-water-supply-temp, chilled-water-return-temp | 900 | Pump on AND (CHWR − CHWS) < 2.2 °C (ΔT). |
| `CHW-2` | `plant` | chiller | chw-diff-pressure, chw-diff-pressure-sp, chw-pump-cmd | 300 | Pump ≥ 87% AND CHW DP < DP SP − 2.2. |
| `CHW-3` | `plant` | chiller | chilled-water-supply-temp, chilled-water-supply-temp-sp, chw-pump-cmd | 300 | Pump on AND \\|CHWS − CHWS SP\\| > 1.22Δ°C. |
| `CHW-4` | `plant` | chiller | chw-flow, chw-pump-cmd | 300 | Pump ≥ 87% AND CHW flow > 69.4 L/s (~1100 US gpm). |
| `HP-1` | `heatpump` | heatpump | discharge-air-temp, zone-air-temp, fan-cmd | 600 | Fan on, zone < 20.56°C, discharge SAT < 29.44°C. |
| `WX-1` | `weather` | weather | outside-air-temp | 300 | OAT sample-to-sample jump > 8.89Δ°C. |
| `CW-OPT-1` | `plant` | chiller, cooling_tower | condenser-water-supply-temp | 900 | CW supply significantly colder than web wet-bulb + design approach (Stull WB) — tower over-cooling / not optimized. |
| `CW-APR-1` | `plant` | chiller, cooling_tower | condenser-water-supply-temp | 900 | At full tower fan speed, leaving CW − web wet-bulb exceeds approach_max (default 4.4 °C Δ, typically 2.8–5.6 °C). Suspect OA→w… |
| `CW-FAN-1` | `plant` | chiller, cooling_tower | condenser-water-supply-temp | 900 | Tower fans at full speed while leaving CW is well above web wet-bulb + design approach (approach + excess_beyond). Fa… |
| `TRIM-1` | `trim` | ahu | duct-static-pressure, vav-pressure-request-sum | 1800 | Duct static high (> 335.934 Pa, equivalent to 1.35 in. w.c.) while VAV pressure requests are low. |
| `TRIM-3` | `trim` | boiler | hot-water-supply-temp, hw-reset-request-sum | 1800 | HW supply > 71 °C while reset requests are low. |
| `TRIM-4` | `trim` | chiller | chilled-water-supply-temp, chw-reset-request-sum | 1800 | CHW supply < 7.2 °C while reset requests are low. |
| `SCHED-1` | `schedule` | ahu | occupied, fan-status | 1800 | Fan running while occupancy is unoccupied (Overview calendar → occ_mode). When zone_t is mapped, also require zone in… |
| `SCHED-247` | `schedule` | ahu, vav, chiller, boiler, heatpump |  | 3600 | Fan or pump (or similar motor proof/command) is on for ≥ always_on_pct of the analysis window — highlights equipment … |
| `CMD-1` | `ahu` | ahu | fan-cmd, fan-status | 600 | Fan command and proven status disagree. |
| `OA-1` | `ahu` | ahu | mixed-air-temp, return-air-temp, outside-air-temp, fan-status | 900 | Estimated OA fraction < 15% with adequate OAT/RAT split. |
| `DMP-1` | `ahu` | ahu | outside-air-temp, mixed-air-temp, outside-air-damper | 900 | Damper ≤ 5% but MAT tracks OAT within 1.11Δ°C — leaking OA damper. |
| `VLV-1` | `ahu` | ahu | discharge-air-temp, discharge-air-temp-sp, cooling-valve | 900 | Cooling valve ≤ 5% AND (SAT < sat_sp − sat_err OR SAT < MAT − mat_leak_delta). Fan proven on when fan_status/fan_cmd … |
| `RESET-1` | `ahu` | ahu | discharge-air-temp-sp, outside-air-temp | 900 | Fan on AND \\|SAT SP − (52 + 0.25×(OAT−65))\\| > 1.67Δ°C. |

---

## Tunable params (summary)

Per-rule slider params are listed under each section in the Pandas/SQL cookbooks. Common patterns:

| Pattern | Examples |
|---------|----------|
| Error / deadband | `duct_static_err`, `sat_err`, `mat_env` |
| Command high/low | `fan_hi`, valve closed ≤ 0.05 |
| Confirm delay | `confirm_seconds` (via `CONFIRM_PARAM`) |
| Sweep scales | `range_scale_*`, `spike_scale_*`, `flatline_tol` |

---

## Validation scenarios

| scenario | expected fault_raw |
|----------|-------------------|
| normal | false |
| obvious_fault | true after confirmation |
| borderline | document sensitivity |
| missing_point | false |
| bad_sensor | false (gated) |

Fixtures: [benchmark strategy](benchmark-strategy.html) · `docs/rules/cookbook/fixtures/`
