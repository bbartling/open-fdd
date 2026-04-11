---
title: Test bench rule catalog
parent: Fault rules for HVAC
nav_order: 3
---

# Test bench rule catalog

Open-FDD ships **two** default rules under [`stack/rules/`](https://github.com/bbartling/open-fdd/tree/master/stack/rules) (`sensor_bounds.yaml`, `sensor_flatline.yaml`). For **extended HVAC, chiller, heat-pump, and weather expression rules** used in lab automation and cookbook examples, the repository also keeps a **reference set** under **`openclaw/bench/rules_reference/`** (not loaded until you copy or upload them).

Each file below links to the copy on **GitHub** (`master` branch) so the published docs site stays in sync with the repo.

## Reference YAML files

| File | GitHub |
|------|--------|
| `ahu_fc1.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc1.yaml) |
| `ahu_fc2.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc2.yaml) |
| `ahu_fc3.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc3.yaml) |
| `ahu_fc4.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc4.yaml) |
| `ahu_fc5.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc5.yaml) |
| `ahu_fc6.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc6.yaml) |
| `ahu_fc7.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc7.yaml) |
| `ahu_fc8.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc8.yaml) |
| `ahu_fc9.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc9.yaml) |
| `ahu_fc10.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc10.yaml) |
| `ahu_fc11.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc11.yaml) |
| `ahu_fc12.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc12.yaml) |
| `ahu_fc13.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc13.yaml) |
| `ahu_fc14.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc14.yaml) |
| `ahu_fc15.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc15.yaml) |
| `ahu_fc16.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_fc16.yaml) |
| `ahu_rule_a.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/ahu_rule_a.yaml) |
| `chiller_flow_fc2.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/chiller_flow_fc2.yaml) |
| `chiller_pump_fc1.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/chiller_pump_fc1.yaml) |
| `hp_discharge_cold_when_heating.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/hp_discharge_cold_when_heating.yaml) |
| `sensor_bounds.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/sensor_bounds.yaml) |
| `sensor_flatline.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/sensor_flatline.yaml) |
| `weather_gust_lt_wind.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/weather_gust_lt_wind.yaml) |
| `weather_rh_out_of_range.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/weather_rh_out_of_range.yaml) |
| `weather_temp_spike.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/weather_temp_spike.yaml) |
| `weather_temp_stuck.yaml` | [link](https://github.com/bbartling/open-fdd/blob/master/openclaw/bench/rules_reference/weather_temp_stuck.yaml) |

## Related docs

- [Fault rules overview](overview) — where live rules live (`stack/rules`) and how to upload or sync.
- [Expression rule cookbook](../expression_rule_cookbook) — AHU, chiller, weather patterns that match many of these files.
- [OpenClaw lab README](https://github.com/bbartling/open-fdd/blob/master/openclaw/README.md) — bench layout including `rules_reference/` and E2E automation.

The former **open-fdd-automated-testing** repo is superseded by the **`openclaw/`** tree in this repository; do not link automation to a separate rules tree.
