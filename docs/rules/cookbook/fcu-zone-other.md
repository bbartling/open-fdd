---
title: FCU and zone_other rules
parent: Rule Cookbook
nav_order: 12
---

# Fan-coil and standalone zone-controller rules

Open-FDD ships nine **FCU-*** rules for fan coils and standalone DDC zone
controllers. They run in the DataFusion product engine and in the external
`open_fdd.rules` pandas oracle. Registry equipment kinds are `zone_other`,
`general`, and `ahu`; the pandas catalog also accepts the historical `zone`
kind. A follower without its own zone sensor may be stamped `general`, while a
controller with its own zone sensor should be `zone_other`.

| Rule | Screening condition | Confirm |
| --- | --- | ---: |
| `FCU-SENSOR-NULL` | Own zone SP exists and zone temperature is null for at least 90% of the window | 0 |
| `FCU-HTG-COIL` | Fan on, heating ≥80%, SAT − zone <5.4°F | 15 min |
| `FCU-CLG-COIL` | Fan on, cooling ≥80%, heat shut, SAT ≥ zone | 15 min |
| `FCU-VALVE-PASS-HTG` | Fan on, both valves shut, SAT − zone >5.4°F | 15 min |
| `FCU-VALVE-PASS-CLG` | Fan on, both valves shut, zone − SAT >5.4°F | 15 min |
| `FCU-DAMPER-POS` | Fan on, command ≥15%, feedback >15 points low | 15 min |
| `FCU-CO2-DAMPER` | Fan on, valid CO₂ >1000 ppm, damper command <10% | 15 min |
| `FCU-DEADBAND` | Cooling SP − heating SP <1°C | 0 |
| `FCU-MODE-CYCLE` | At least four heat/cool valve mode transitions in the window | 0 |

Commands accept either 0–1 or 0–100 values. Fan proof prefers
`fan_status`; `fan_cmd > 10%` is the fallback. CO₂ below 300 ppm is treated
as invalid rather than a ventilation fault.

## Unit boundary

The DataFusion engine rewrites canonical temperature roles such as `sat` and
`zone_t` through `history_si`, so FCU temperature-difference thresholds are
expressed in °F (5.4°F = 3°C). The `cooling_sp` and `heating_sp` fields are
site pass-through setpoints and are intentionally evaluated in °C. Package
authors must not map Fahrenheit setpoints into those two pass-through roles.

## Loading and evidence

The files live in `sql_rules/` and are registered in
`sql_rules/registry.yaml`; no site registry fork or
`OPENFDD_SQL_RULES_DIR` override is needed. They remain labeled
`sql_screening`: focused predicate fixtures cover pandas behavior and
DataFusion SQL is compiled/executed by Rust rule tests, but production site-soak
evidence is still required before claiming duration or site parity. The rules
are not marked `dashboard_wired` until issue #1029 lands.

