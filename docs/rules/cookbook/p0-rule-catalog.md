---
title: P0 rule catalog (metadata)
parent: Rule Cookbook
nav_order: 11
---

# P0 rule catalog — full metadata

Standards-first metadata for every **validated** cookbook rule (vibe19 catalog). Detection SQL/Pandas live in the [SQL](datafusion-sql-cookbook.html) and [Pandas](pandas-cookbook.html) cookbooks.

{: .important }
All **thresholds are defaults** — site-adjustable. **confirmation_seconds** default **300** unless noted.

---

## Validated rules

| id | family | equipment | roles | confirmation_s | equation |
|----|--------|-----------|-------|----------------:|----------|
| `SV-RANGE` | `sensor` | ahu, vav, chiller, boiler, weather, zone, heatpump |  | 300 | Any modeled sensor reads outside its physical hard range (e.g. OAT −60–130°F, SAT 30–150°F, CHWS 30–80°F). |
| `SV-FLATLINE` | `sensor` | ahu, vav, chiller, boiler, weather, zone, heatpump |  | 300 | Sensor value unchanged (Δ ≤ tolerance) across the flatline window — stuck / frozen sensor. |
| `SV-SPIKE` | `sensor` | ahu, vav, chiller, boiler, weather, zone, heatpump |  | 300 | Sample-to-sample jump exceeds the physical spike limit for the sensor type. |
| `SV-STALE` | `sensor` | ahu, vav, chiller, boiler, weather, zone, heatpump |  | 300 | All modeled sensors unchanged over the stale window — data feed likely dropped. |
| `SV-RATE` | `sensor` | ahu, vav, chiller, boiler, weather, zone, heatpump |  | 600 | Implausible sustained rate-of-change for mapped sensors. Thresholds depend on quantity, location, and operating state… |
| `PID-HUNT-1` | `control` | ahu, vav, chiller, boiler, heatpump |  | 300 | Rolling 1h total variation of any 0–100% control output (dampers, valves, fan speeds, heat/cool cmds) with span ≥20%,… |
| `FC1` | `ahu` | ahu | duct-static-pressure, duct-static-pressure-sp, fan-cmd | 300 | Fan ≥ 87% AND duct static < static SP − 0.12 in.w.c. |
| `FC2` | `ahu` | ahu | mixed-air-temp, outside-air-temp, return-air-temp, fan-cmd | 600 | Fan on AND MAT + mix_tol < min(RAT − mix_tol, OAT − mix_tol) (≡ MAT < min(RAT, OAT) − 2·mix_tol; default mix_tol = 1.… |
| `FC3` | `ahu` | ahu | mixed-air-temp, outside-air-temp, return-air-temp, fan-cmd | 600 | Fan on AND MAT − mix_tol > max(RAT + mix_tol, OAT + mix_tol) (≡ MAT > max(RAT, OAT) + 2·mix_tol; default mix_tol = 1.… |
| `FC4` | `ahu` | ahu | outside-air-damper, cooling-valve, fan-cmd | 3600 | More than 5 operating-mode entry transitions in any hour (heating/econ/mech modes). |
| `FC5` | `ahu` | ahu | discharge-air-temp, mixed-air-temp, fan-cmd, heating-valve | 600 | Fan on AND heating > 1% AND SAT + mix_tol ≤ MAT − mix_tol + 0.55°F (default mix_tol = 1.15°F). |
| `FC6` | `ahu` | ahu | mixed-air-temp, outside-air-temp, return-air-temp, vav-total-airflow | 600 | \\|RAT−OAT\\| ≥ 5°F AND \\|estimated OA% − design min OA%\\| > 15% in heating/mech-only modes. |
| `FC7` | `ahu` | ahu | discharge-air-temp, discharge-air-temp-sp, fan-cmd, heating-valve | 600 | Fan on AND heating > 90% AND SAT < SAT SP − 1.0°F. |
| `FC8` | `ahu` | ahu | discharge-air-temp, mixed-air-temp, outside-air-damper, cooling-valve | 600 | Economizer open, CHW < 10%, \\|SAT − 0.55°F − MAT\\| > √(supply_tol²+mix_tol²). |
| `FC9` | `ahu` | ahu | outside-air-temp, discharge-air-temp-sp, outside-air-damper, cooling-valve | 600 | Economizer open, CHW < 10%, OAT − mix_tol > SAT SP − 0.55°F + mix_tol. |
| `FC10` | `ahu` | ahu | mixed-air-temp, outside-air-temp, outside-air-damper, cooling-valve | 600 | CHW > 1%, economizer > 90%, \\|MAT − OAT\\| > √(mix_tol²+mix_tol²). |
| `FC11` | `ahu` | ahu | outside-air-temp, discharge-air-temp-sp, outside-air-damper, cooling-valve | 600 | CHW > 1%, economizer > 90%, OAT + mix_tol < SAT SP − 0.55°F − mix_tol. |
| `FC12` | `ahu` | ahu | discharge-air-temp, mixed-air-temp, outside-air-damper, cooling-valve | 600 | CHW > 1%, SAT − supply_tol − 0.55°F > MAT + mix_tol at min or full economizer. |
| `FC13` | `ahu` | ahu | discharge-air-temp, discharge-air-temp-sp, outside-air-damper, cooling-valve | 600 | CHW > 1%, SAT > SAT SP + 1.0°F at min or full economizer. |
| `FC14` | `ahu` | ahu | cooling-coil-entering-temp, cooling-coil-leaving-temp, outside-air-damper, cooling-valve | 600 | Cooling coil ΔT ≥ √(mix_tol²+mix_tol²)+0.55°F while coil should be inactive. |
| `FC15` | `ahu` | ahu | heating-coil-entering-temp, heating-coil-leaving-temp, outside-air-damper, cooling-valve | 600 | Heating coil ΔT ≥ √(mix_tol²+mix_tol²)+0.55°F while coil should be inactive. |
| `AHU-SATDEV` | `ahu` | ahu | discharge-air-temp, discharge-air-temp-sp | 600 | \\|SAT − SAT SP\\| > 5°F. |
| `AHU-DUCTHI` | `ahu` | ahu | duct-static-pressure, duct-static-pressure-sp | 300 | Duct static > static SP + margin. Evaluates when fan is proven on OR duct static itself exceeds pressure_on_min (catc… |
| `AHU-SIMUL` | `ahu` | ahu | heating-valve, cooling-valve | 300 | Heating valve > 10% AND cooling valve > 10% at once. |
| `OAT-METEO` | `ahu` | ahu | outside-air-temp, web-outside-air-temp | 900 | BAS OAT sensor differs from Open-Meteo dry bulb by more than 5°F. |
| `ECON-1` | `ahu` | ahu | fan-cmd, outside-air-damper, outside-air-temp | 600 | Fan on, OA damper < 5%, OAT > 55°F (should be economizing). |
| `ECON-2` | `ahu` | ahu | outside-air-temp, outside-air-damper | 300 | OAT > 63°F AND OA damper > 42% (should be at minimum). |
| `ECON-3` | `ahu` | ahu | outside-air-damper, cooling-valve | 300 | Web free-cooling opportunity: 60°F ≤ dry-bulb < 72°F AND dewpoint < 60°F (dewpoint from web sensor or calculated from… |
| `ECON-4` | `ahu` | ahu | mixed-air-temp, return-air-temp, outside-air-temp, fan-cmd | 600 | Fan on, \\|RAT−OAT\\| > 2.2°F, estimated OA fraction < 21%. |
| `ECON-5` | `ahu` | ahu | preheat-leaving-temp, discharge-air-temp-sp, outside-air-temp, heating-valve | 600 | Preheat leaving air > 2.2°F above target while preheat active. |
| `ECON-6` | `ahu` | ahu | outside-air-damper | 600 | Web dry-bulb < 25°F AND OA damper above winter min-OA ceiling (default 25%). AHU should be at minimum OA in cold weat… |
| `ECON-7` | `ahu` | ahu | outside-air-damper | 600 | Economizer-OK web weather: dew point < 60°F AND dry-bulb < 72°F (above a 35°F freeze-guard floor; dewpoint from web s… |
| `MECH-OAT-1` | `ahu` | ahu, chiller, heatpump |  | 600 | Proven DX/chiller mechanical cooling while web dry-bulb < 60°F. Uses compressor/chiller/pump/amps/power proof — not A… |
| `CHW-NOLOAD-1` | `plant` | chiller |  | 1800 | Chiller/plant proven running while building load is satisfied: all mapped zones inside comfort band OR all mapped AHU… |
| `VAV-1` | `vav` | vav, zone | zone-air-temp | 900 | Zone temp < 70°F or > 75°F. |
| `VAV-3` | `vav` | vav | outside-air-temp, reheat-valve | 300 | Air flowing AND OAT > 78°F AND reheat valve > 52%. |
| `VAV-4` | `vav` | vav | damper | 900 | Air flowing AND damper > 97.5% sustained across the window. |
| `VAV-5` | `vav` | vav | zone-airflow, damper | 900 | Airflow > 50 cfm while damper < 10% (implausible flow). |
| `VAV-REHEAT` | `vav` | vav | reheat-valve, vav-discharge-air-temp, vav-inlet-air-temp | 900 | Air flowing AND reheat valve > 30% AND box discharge temp rises < 3°F above duct inlet (air from AHU) — stuck or fail… |
| `VAV-AHU-LEAVE` | `vav` | vav | vav-discharge-air-temp, ahu-discharge-air-temp | 900 | Air flowing AND \\|VAV discharge − parent AHU SAT\\| > band. Needs package topology (vav_to_ahu) so ahu_sat is enrich… |
| `VAV-7` | `vav` | vav | zone-airflow | 900 | Flow below min SP (when mapped), OR airflow stays flat (low rolling std) at a high mean while air is on (mins too hig… |
| `CHW-1` | `plant` | chiller | chilled-water-supply-temp, chilled-water-return-temp | 900 | Pump on AND (CHWR − CHWS) < 4°F. |
| `CHW-2` | `plant` | chiller | chw-diff-pressure, chw-diff-pressure-sp, chw-pump-cmd | 300 | Pump ≥ 87% AND CHW DP < DP SP − 2.2. |
| `CHW-3` | `plant` | chiller | chilled-water-supply-temp, chilled-water-supply-temp-sp, chw-pump-cmd | 300 | Pump on AND \\|CHWS − CHWS SP\\| > 2.2°F. |
| `CHW-4` | `plant` | chiller | chw-flow, chw-pump-cmd | 300 | Pump ≥ 87% AND CHW flow > 1100 gpm. |
| `HP-1` | `heatpump` | heatpump | discharge-air-temp, zone-air-temp, fan-cmd | 600 | Fan on, zone < 69°F, discharge SAT < 85°F. |
| `WX-1` | `weather` | weather | outside-air-temp | 300 | OAT sample-to-sample jump > 16°F. |
| `CW-OPT-1` | `plant` | chiller, cooling_tower | condenser-water-supply-temp | 900 | CW supply significantly colder than web wet-bulb + design approach (Stull WB) — tower over-cooling / not optimized. |
| `CW-APR-1` | `plant` | chiller, cooling_tower | condenser-water-supply-temp | 900 | At full tower fan speed, leaving CW − web wet-bulb exceeds approach_max (default 8°F, typically 5–10°F). Suspect OA→w… |
| `CW-FAN-1` | `plant` | chiller, cooling_tower | condenser-water-supply-temp | 900 | Tower fans at full speed while leaving CW is well above web wet-bulb + design approach (approach + excess_beyond). Fa… |
| `TRIM-1` | `trim` | ahu | duct-static-pressure, vav-pressure-request-sum | 1800 | Duct static high (> 1.35 in.w.c.) while VAV pressure requests are low. |
| `TRIM-3` | `trim` | boiler | hot-water-supply-temp, hw-reset-request-sum | 1800 | HW supply > 160°F while reset requests are low. |
| `TRIM-4` | `trim` | chiller | chilled-water-supply-temp, chw-reset-request-sum | 1800 | CHW supply < 45°F while reset requests are low. |
| `SCHED-1` | `schedule` | ahu | occupied, fan-status | 1800 | Fan running while occupancy is unoccupied (Overview calendar → occ_mode). When zone_t is mapped, also require zone in… |
| `SCHED-247` | `schedule` | ahu, vav, chiller, boiler, heatpump |  | 3600 | Fan or pump (or similar motor proof/command) is on for ≥ always_on_pct of the analysis window — highlights equipment … |
| `CMD-1` | `ahu` | ahu | fan-cmd, fan-status | 600 | Fan command and proven status disagree. |
| `OA-1` | `ahu` | ahu | mixed-air-temp, return-air-temp, outside-air-temp, fan-status | 900 | Estimated OA fraction < 15% with adequate OAT/RAT split. |
| `DMP-1` | `ahu` | ahu | outside-air-temp, mixed-air-temp, outside-air-damper | 900 | Damper ≤ 5% but MAT tracks OAT within 2°F — leaking OA damper. |
| `VLV-1` | `ahu` | ahu | discharge-air-temp, discharge-air-temp-sp, cooling-valve | 900 | Cooling valve ≤ 5% AND (SAT < sat_sp − sat_err OR SAT < MAT − mat_leak_delta). Fan proven on when fan_status/fan_cmd … |

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
