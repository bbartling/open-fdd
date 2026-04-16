---
title: Test bench rule catalog
parent: Fault rules for HVAC
nav_order: 3
---

# Rule YAML catalog (in this repository)

Example and test rules live next to the engine sources. Use them as templates for your own `rules_dir`.

## `open_fdd/tests/fixtures/rules/` (pytest)

| File | Purpose |
|------|---------|
| [`weather_gust_lt_wind.yaml`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/tests/fixtures/rules/weather_gust_lt_wind.yaml) | Weather / wind gust check |
| [`weather_rh_out_of_range.yaml`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/tests/fixtures/rules/weather_rh_out_of_range.yaml) | RH bounds |
| [`weather_temp_spike.yaml`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/tests/fixtures/rules/weather_temp_spike.yaml) | Temperature spike |
| [`weather_temp_stuck.yaml`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/tests/fixtures/rules/weather_temp_stuck.yaml) | Temperature stuck |
| [`test_flatline_sat.yaml`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/tests/fixtures/rules/test_flatline_sat.yaml) | Flatline SAT |
| [`test_sensor_flatline_1774618711.yaml`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/tests/fixtures/rules/test_sensor_flatline_1774618711.yaml) | Sensor flatline test |

## `examples/AHU/rules/` (notebooks / demos)

| File | Purpose |
|------|---------|
| [`sensor_bounds.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/rules/sensor_bounds.yaml) | Bounds example |
| [`sensor_flatline.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/rules/sensor_flatline.yaml) | Flatline example |
| [`sat_operating_band.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/rules/sat_operating_band.yaml) | SAT band |

## Related docs

- [Fault rules overview](overview)
- [Expression rule cookbook](../expression_rule_cookbook)
