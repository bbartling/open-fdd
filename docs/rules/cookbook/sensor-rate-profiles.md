---
title: Sensor rate profiles (SV-SLEW)
parent: Rule Cookbook
nav_order: 13
permalink: /rules/cookbook/sensor-rate-profiles/
---

# Sensor rate profiles — research conclusion and SV-SLEW

Machine-readable defaults: [`sql_rules/profiles/sensor_rate_profiles.yaml`](../../../sql_rules/profiles/sensor_rate_profiles.yaml).  
Executable rule: **`SV-SLEW`** (`sv_slew.sql`). Abrupt jumps remain **`SV-SPIKE`**.

## Research conclusion

There is **no universal ASHRAE table** that defines one allowable “change per hour” for every HVAC sensor. A valid rate-of-change limit depends on:

* Sensor type and physical location  
* Equipment operating state  
* Whether a fan, pump, compressor, valve, or damper just changed state  
* Sampling interval  
* Sensor resolution and accuracy  
* Expected thermal or mechanical inertia  

Published HVAC FDD research commonly separates **off-cycle**, **startup/transient**, and **steady-state** operation rather than applying one threshold continuously. HVAC systems may remain transient for roughly **30 minutes** after operational changes, and steady-state FDD methods often intentionally remove startup data.

That distinction is the main improvement needed for Open-FDD slew validation.

A discharge-air temperature sensor may legitimately move **20 °F/h** after a cooling coil is energized, while a **zone** sensor moving 20 °F/h is likely bad data, a badly located sensor, or an extreme local disturbance.

### Do not implement

```text
abs(value_now - value_one_hour_ago) > universal_limit
```

### Implement as context-sensitive slew validation

```text
sensor type
+ sensor location
+ equipment type
+ operating mode
+ time since state transition
+ sampling quality
= applicable rate threshold
```

### Operating states

| State | Meaning |
|-------|---------|
| `OFF_OR_STABLE` | Equipment off or no meaningful command/state change |
| `STARTUP_TRANSIENT` | Within a configurable period after fan, pump, compressor, valve, stage, or mode transition |
| `RUNNING_STEADY` | Equipment running and transition timer expired |

ASHRAE Guideline 36 similarly conditions AHU diagnostics on operating states and applies delays to suppress false alarms. Open-FDD mirrors that idea for **sensor rate** validation.

## Separate these four faults

| Rule | Meaning |
|------|---------|
| `SV-RANGE` | Value is physically or operationally implausible |
| `SV-FLATLINE` | Value does not change enough for too long |
| `SV-SPIKE` | One or a few abrupt discontinuities (sample-to-sample jump) |
| `SV-SLEW` | Sustained change is too fast for that sensor and state |

A sensor may pass range validation while failing rate validation. Example: zone temperature 72 → 78 → 72 °F in ten minutes — every value is physically possible, but the behavior is highly suspicious.

## Metrics (full intent)

For every series calculate (SQL first cut implements time-normalized point-to-point + gap reject + extreme short-window + persistence; slopes/robust estimators are documented for later):

* Point-to-point normalized rate (°F/h, pp/h, ppm/h, …)  
* 5-minute and 15-minute net change  
* 60-minute net change  
* Robust 15-minute and 60-minute slope (Theil–Sen / median slope preferred)  
* Rolling range, violation counts, longest continuous violation  

```text
rate_per_hour = abs(value.diff) / timestamp.diff_seconds * 3600
```

Do **not** assume all samples are 5 or 15 minutes apart. Reject or mark intervals where:

* Timestamp difference is zero or negative  
* Gap exceeds `max_gap_factor ×` expected interval (default 3×)  
* Either endpoint is missing  
* Units cannot be resolved  
* Sensor role is ambiguous  

## Persistence and extremes

Defaults:

```text
minimum_violation_samples: 2
minimum_violation_minutes: 10
minimum_data_coverage: 0.80
```

CO₂ and zone conditions: prefer **15–30 minutes** persistence.

Allow **immediate** detection for extreme impossible jumps, for example:

* Zone temperature &gt; 15 °F in 5 minutes  
* CO₂ &gt; 3000 ppm in 5 minutes  
* RH &gt; 40 percentage points in 5 minutes  
* Building pressure &gt; configured sensor span in one interval  

## Transition windows (defaults)

| Equipment event | Suppression / transient window |
|-----------------|--------------------------------|
| AHU supply fan start/stop | 20 minutes |
| RTU compressor stage change | 15 minutes |
| Heating/cooling valve opening | 10 minutes |
| Boiler enable | 30 minutes |
| Chiller enable | 30 minutes |
| Hydronic pump start/stop | 10 minutes |
| Economizer mode change | 15 minutes |
| Occupancy mode transition | 30 minutes |
| Humidifier enable | 20 minutes |

Do not silently drop these intervals as normal. Score them against **transient** thresholds and treat them as `STARTUP_TRANSIENT`.

## Proposed default rate limits

Engineering defaults for **screening** — not code or manufacturer limits. Tunable via rule parameters / site profiles (React SQL FDD params), not hardcoded per site.

Use both a short-window rate (5–15 minutes preferred) and a rolling one-hour net change or robust slope. Defaults below are **per hour** unless noted.

### Temperature (°F/h)

| Sensor location | Stable/steady limit | Startup/transient limit | Metric (°C/h) |
|-----------------|--------------------:|------------------------:|---------------|
| Zone/room air | 4 | 8 | 2.2 ; 4.4 |
| Return air | 6 | 12 | 3.3 ; 6.7 |
| Outdoor air | 12 | 20 | 6.7 ; 11.1 |
| Mixed air | 12 | 30 | 6.7 ; 16.7 |
| AHU supply/discharge | 10 | 35 | 5.6 ; 19.4 |
| Heating-coil leaving | 15 | 50 | 8.3 ; 27.8 |
| Cooling-coil leaving | 12 | 35 | 6.7 ; 19.4 |
| VAV discharge | 12 | 35 | 6.7 ; 19.4 |
| Chilled-water supply | 6 | 15 | 3.3 ; 8.3 |
| Chilled-water return | 8 | 15 | 4.4 ; 8.3 |
| Hot-water supply | 15 | 50 | 8.3 ; 27.8 |
| Hot-water return | 12 | 30 | 6.7 ; 16.7 |
| Condenser-water S/R | 10 | 20 | 5.6 ; 11.1 |
| Refrigerant temperature | 40 | 150 | 22.2 ; 83.3 |

ASHRAE Standard 55 occupant-comfort drift guidance (~**4 °F / 2.2 °C** over one hour) is a reasonable **warning** basis for zone temperature — not an automatic “sensor broken” declaration:

```text
zone_air_temperature:
  warning: 4.0 degF/hour
  fault:   6.0 degF/hour
  extreme: 10.0 degF/hour
```

### Relative humidity (percentage points / h)

| Sensor location | Stable/steady | Startup/transient |
|-----------------|--------------:|------------------:|
| Zone RH | 10 | 15 |
| Return-air RH | 12 | 20 |
| Outdoor-air RH | 25 | 40 |
| Mixed-air RH | 20 | 35 |
| Supply/discharge RH | 20 | 45 |
| After humidifier/dehumidifier | 25 | 60 |

Use **percentage points**, not percent change (40% → 55% RH = 15 pp). Prefer dew-point consistency when temperature and RH are both available.

### CO₂ (ppm/h)

| Sensor location | Stable/steady | Occupancy/startup |
|-----------------|--------------:|------------------:|
| Normal office zone | 500 | 1200 |
| Classroom/conference | 800 | 2000 |
| Return air | 500 | 1000 |
| Outdoor air | 150 | 300 |
| Dense assembly | 1000 | 2500 |

```text
zone_co2:
  noise_deadband_ppm: 100
  warning_rate_ppm_per_hour: 500
  fault_rate_ppm_per_hour: 1200
  extreme_rate_ppm_per_hour: 2500
  minimum_persistence_minutes: 15
```

Do **not** treat 1000 ppm as a universal IAQ limit.

### Air pressure (in. w.c. / h)

| Sensor location | Stable/steady | Startup/transient |
|-----------------|--------------:|------------------:|
| Building pressure | 0.10 | 0.30 |
| Duct static | 0.75 | 3.0 |
| Filter ΔP | 0.25 | 1.0 |
| VAV inlet/flow ΔP | 0.5 | 2.0 |

Metric: 0.10 in. w.c. ≈ 24.9 Pa; 1.00 ≈ 249.1 Pa; 3.00 ≈ 747.2 Pa.

For duct static, prefer short-window median / slope and fan/VFD transition context over hourly net change alone.

### Hydronic pressure (psi/h)

| Sensor location | Stable/steady | Startup/transient |
|-----------------|--------------:|------------------:|
| Loop ΔP | 5 | 20 |
| Pump suction/discharge | 10 | 40 |
| Static system pressure | 3 | 10 |

Prefer % of design span when known (steady warning ~20%/h of span; transient ~75%/h).

### Flow (normalized)

| Sensor type | Stable/steady | Startup/transient |
|-------------|--------------:|------------------:|
| VAV airflow | 100% of design/h | 400% of design/h |
| AHU outdoor airflow | 75% of design/h | 300% of design/h |
| AHU supply airflow | 75% of design/h | 300% of design/h |
| CHW/HW flow | 75% of design/h | 300% of design/h |

### Commands / feedback (not environmental)

Valve/damper/VFD movement belongs with hunting diagnostics ([PID-HUNT-1](pid-hunt-1.html)), not environmental slew limits.

| Point | Settled | Transition |
|-------|---------|------------|
| Valve command/position | ≤100%/h | up to 600%/h |
| Damper command/position | ≤150%/h | up to 1200%/h |
| VFD speed | ≤100%/h | up to 600%/h |

## Profile model

```text
SensorRateProfile:
  profile_id
  quantity
  location
  canonical_unit
  haystack_roles[]          # zone_t, sat, oa_t, ...
  steady_warning_per_hour
  steady_fault_per_hour
  transient_warning_per_hour
  transient_fault_per_hour
  extreme_interval_change
  extreme_interval_minutes
  persistence_minutes
  transition_window_minutes
  normalize_by              # optional: design_flow | sensor_span
```

Example profile IDs: `zone_air_temperature`, `return_air_temperature`, `outside_air_temperature`, `mixed_air_temperature`, `supply_air_temperature`, `coil_leaving_air_temperature`, `zone_relative_humidity`, `supply_air_relative_humidity`, `zone_co2`, `outside_air_co2`, `duct_static_pressure`, `building_static_pressure`, `filter_differential_pressure`, `hydronic_differential_pressure`, `vav_airflow`, `ahu_airflow`, `water_flow`, `damper_position`, `valve_position`, `vfd_speed`.

Project Haystack already distinguishes zone / outside / return / mixed / discharge / pressure / humidity / CO₂ / flow. SV-SLEW consumes those roles when mapped.

## SQL first cut (honest scope)

`SV-SLEW` currently evaluates time-normalized rates for pivot roles that already exist (`zone_t`, `sat`, `rat`, `mat`, `oa_t`, CHW/HW temps, `oa_h`, `duct_static`), with:

* Gap rejection via `to_unixtime` Δt  
* Steady vs transient fault thresholds (fan-status transition window when available)  
* Zone extreme short-window bypass  
* Confirmation streak persistence  

CO₂, flow, and valve/damper profiles are registered in YAML and this doc for tuning; SQL branches ship when those roles are present on the historian pivot.
