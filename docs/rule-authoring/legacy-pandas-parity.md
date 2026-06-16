---
title: Legacy pandas parity
parent: Rule authoring (v1)
nav_order: 4
---

# Legacy pandas parity matrix

Maps the historical **pandas gist** fault classes to Open-FDD **v1 Arrow** (and optional SQL) equivalents.

**Source gist (legacy, not maintained):** [FaultConditionOne–Fifteen](https://gist.github.com/bbartling/11cb1cb1295a1bfba5c167efa02122ef)

**Status legend**

| Status | Meaning |
|--------|---------|
| **exact parity** | Regression test proves equivalent flag behavior on fixture data |
| **modernized** | Same intent; Arrow implementation differs (documented) |
| **retired** | No v1 edge path — catalog/metadata only |
| **pending** | Not yet ported to Arrow module + test |

Do **not** claim exact parity without a named test file.

---

## Helper utilities

| Legacy | Summary | Modern equivalent | Status | Tests |
|--------|---------|-------------------|--------|-------|
| `HelperUtils.convert_to_float` | Cast column to float | Ingest typing + `pc.cast(..., pa.float64())` | modernized | ingest / lint |
| `HelperUtils.isfloat` / float checks | Validate analog columns | Rule Lab lint + bridge validation | modernized | `test_rule_kit` |
| `check_range_less_than_one` | Command must be ≤ 1 after scaling | `norm_cmd_array()` | modernized | `test_cookbook.py` |
| `np.maximum` / `np.minimum` | Element-wise min/max | `pc.max` / `pc.min` | modernized | cookbook tests |
| pandas `rolling` / `resample` | Window aggregates | `arrow_rolling_*`, `arrow_rolling_sum` | modernized | `test_windows.py` |

---

## GL36 fault conditions (gist classes)

| Legacy | Legacy behavior (summary) | Modern helper / module | Fault code | Status | Test coverage |
|--------|---------------------------|------------------------|------------|--------|---------------|
| **FC1** `FaultConditionOne` | Duct static below SP at high supply VFD | `duct_static_low_at_full_fan` pattern — [Rule A]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}) | **AHU-A** | modernized | python-recipes modules; bench smokes |
| **FC2** `FaultConditionTwo` | MAT below min(RAT−Δ, OAT−Δ) with fan on | `mixing_envelope` / Rules B & C | **AHU-D** | modernized | cookbook / bench |
| **FC3** `FaultConditionThree` | MAT above max(RAT+Δ, OAT+Δ) with fan on | `mixing_envelope` high side | **AHU-D** | modernized | cookbook / bench |
| **FC4** `FaultConditionFour` | Hourly AHU OS mode edges > `delta_os_max` | `pid_hunting_command_mask`, `pid_hunting_ahu_os_mask`, `pid_hunting_fc4.py` | **AHU-G**, **VAV-F**, **CH-G**, **RTU-E** | **modernized** | `test_legacy_fc4_parity_or_modernization.py`, `test_cookbook.py` |
| **FC5** `FaultConditionFive` | SAT low vs MAT when heating | Rule D pattern | **AHU-B** | modernized | python-recipes-arrow |
| **FC6** `FaultConditionSix` | SAT high vs MAT when cooling (multi-mode) | Rules J/K patterns | **AHU-B**, **AHU-C** | modernized | python-recipes-arrow |
| **FC7** `FaultConditionSeven` | SAT low, full heating valve | Rule E | **AHU-C** | modernized | python-recipes-arrow |
| **FC8** `FaultConditionEight` | Econ + mech cooling, MAT ≠ OAT | Rule H | **AHU-E** | modernized | python-recipes-arrow |
| **FC9** `FaultConditionNine` | Econ-only, MAT ≠ OAT | Rule I | **AHU-E** | modernized | python-recipes-arrow |
| **FC10** `FaultConditionTen` | Ambient warm, free cooling available | Rule G | **AHU-E** | modernized | python-recipes-arrow |
| **FC11** `FaultConditionEleven` | SAT ≠ MAT in econ mode | Rule F | **AHU-E** | modernized | python-recipes-arrow |
| **FC12** `FaultConditionTwelve` | Cooling coil ΔT when valves closed | Rule L | **CH-C** | modernized | python-recipes-arrow |
| **FC13** `FaultConditionThirteen` | Heating coil ΔT when valves closed | Rule M | **AHU-B** | modernized | python-recipes-arrow |
| **FC14** `FaultConditionFourteen` | Complex multi-mode SAT/MAT (gist) | Split into Rules D/E/F/J/K modules | **AHU-B**, **AHU-C**, **AHU-E** | modernized | python-recipes-arrow |
| **FC15** `FaultConditionFifteen` | VAV / zone specific (gist) | VAV bounds, flatline, damper rules | **VAV-C**, **VAV-D** | modernized | starter pack / bench |

---

## Fault Rule 4 (FC4) — modernized hunting detector

### Legacy (pandas gist)

1. Derive four boolean AHU operating modes (heating, econ-only cooling, econ+mech, mech-only).
2. Cast modes to integers, **resample hourly**, count rising edges per mode.
3. Flag when any hourly transition count exceeds `delta_os_max`.

### Modern (Open-FDD v1)

Legacy FC4 has been **modernized** into an Arrow-native **PID / control hunting** detector:

| Mode | API | Detects |
|------|-----|---------|
| `command` (default) | `pid_hunting_command_mask` | Excessive significant steps on one analog command (damper, valve, VFD, cooling %) |
| `ahu_os` | `pid_hunting_ahu_os_mask` | Excessive changes in a 4-bit operating-state bitmap (economizer, fan, heat, cool) |

Configuration: `delta_os_max`, `hunting_window_samples` or `hunting_window_hours`, `min_active_command`, `min_command_delta`, column names in `cfg`.

**There is no strict legacy compatibility mode** that reproduces pandas hourly `resample("H")` edge counting by default. If exact hourly OS-edge parity is required later, it would need a dedicated legacy mode plus regression fixtures from the gist — not claimed today.

Recommended module: `workspace/data/rules_py/pid_hunting_fc4.py` with `cfg["hunting_mode"]` of `command` or `ahu_os`.

---

## Default YAML starter pack (`open_fdd/default_rules/`)

| YAML file | Executable in v1? | Arrow replacement |
|-----------|-------------------|-------------------|
| `01_vav_zone_temp_bounds_occupied.yaml` | No — metadata only | `sensor_bounds_mask` + occupied gate → **VAV-C** |
| `02_vav_zone_temp_flatline_occupied.yaml` | No | `sensor_flatline_mask` → **VAV-C** |
| `03_vav_damper_command_extreme_flatline.yaml` | No | `flatline_1h_mask` on damper cmd → **VAV-D** |
| `04_ahu_runtime_outside_schedule.yaml` | No | schedule / after-hours helpers → **BLD-C** |
| `05_ahu_duct_static_pressure_not_maintained.yaml` | No | Rule A module → **AHU-A** |
| `06_ahu_internal_temp_sensor_bounds.yaml` | No | `sensor_bounds_mask` → **AHU-C** |
| `07_ahu_internal_temp_sensor_flatline.yaml` | No | `sensor_flatline_mask` → **AHU-C** |

YAML retains **inputs**, **params**, and legacy **expression** text for migration reference only.

---

## Fault code mapping

| Legacy | Modern |
|--------|--------|
| Numeric `VAV-03`, `AHU-03` | Letter codes `VAV-C`, `AHU-C` |
| `fc4_flag`, `FC4` | **AHU-G** / **VAV-F** / **CH-G** / **RTU-E** (equipment-specific assignment) |
| `flag:` in YAML | `fault_code` in Rule Lab metadata |

Bridge `LEGACY_CODE_MAP` resolves old portfolio strings where needed.

---

## Related

- [Expression cookbook — GL36 table]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}#gl36-inspired-ahu-rules-legacy-expression--fault-code)
- [Python recipes (full library)]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }})
- [Arrow rule contract]({{ "/rule-authoring/arrow-rule-contract/" | relative_url }})
