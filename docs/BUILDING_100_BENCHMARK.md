# Rust + DataFusion parity benchmark

Generated: 2026-07-09 18:15 UTC

- building: `BUILDING_100`
- tolerance: `0.5`
- rules compared: 19
- equipment compared: 48
- pass: 368
- fail: 0
- skipped (missing roles): 11
- python-only keys: 162
- sql-only keys: 616
- max abs delta: 0.1667
- max pct delta: 100.00%
- material failure: true

## Summary by rule

| rule | pass | fail | skipped | max Δ | max % | worst equipment |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| FC7 | 0 | 0 | 2 | 0.000 | - | - |
| FC12 | 2 | 0 | 0 | 0.000 | - | - |
| FC9 | 2 | 0 | 0 | 0.000 | - | - |
| FC13-SAT-HIGH | 2 | 0 | 0 | 0.000 | - | - |
| ECON-1 | 2 | 0 | 0 | 0.000 | - | - |
| FC1 | 2 | 0 | 0 | 0.000 | - | - |
| ECON-5 | 0 | 0 | 2 | 0.000 | - | - |
| FC11 | 2 | 0 | 0 | 0.000 | - | - |
| FC10 | 2 | 0 | 0 | 0.000 | - | - |
| FC8 | 2 | 0 | 0 | 0.000 | - | - |
| OAT-METEO | 4 | 0 | 0 | 0.000 | - | - |
| ECON-4 | 2 | 0 | 0 | 0.000 | - | - |
| ECON-2 | 2 | 0 | 0 | 0.000 | - | - |
| FC2 | 2 | 0 | 0 | 0.000 | - | - |
| FC3 | 2 | 0 | 0 | 0.000 | - | - |
| VAV-1 | 84 | 0 | 1 | 0.000 | - | - |
| ZONE-COMFORT-PCT | 42 | 0 | 1 | 0.000 | - | - |
| AVG-ZONE-TEMP | 126 | 0 | 1 | 0.000 | - | - |
| FAULT-ELAPSED-HOURS | 84 | 0 | 1 | 0.000 | - | - |
| FAN-RUNTIME-HOURS | 4 | 0 | 3 | 0.000 | - | - |

## Proven parity

- `FC12`
- `FC9`
- `FC13-SAT-HIGH`
- `ECON-1`
- `FC1`
- `FC11`
- `FC10`
- `FC8`
- `OAT-METEO`
- `ECON-4`
- `ECON-2`
- `FC2`
- `FC3`
- `VAV-1`
- `ZONE-COMFORT-PCT`
- `AVG-ZONE-TEMP`
- `FAULT-ELAPSED-HOURS`
- `FAN-RUNTIME-HOURS`

## Near parity

_None._

## Material mismatch

_None._

## Skipped due to missing roles

- `FC7` / `AHU_1`: missing roles: htg_valve_pct
- `ECON-5` / `AHU_1`: missing roles: preheat_leave_t, htg_valve_pct
- `FC7` / `AHU_2`: missing roles: htg_valve_pct
- `ECON-5` / `AHU_2`: missing roles: preheat_leave_t, htg_valve_pct
- `FAN-RUNTIME-HOURS` / `BOILERS_PUMPS`: missing roles: fan_cmd
- `FAN-RUNTIME-HOURS` / `CHILLER_1`: missing roles: fan_cmd
- `FAN-RUNTIME-HOURS` / `CHILLER_2`: missing roles: fan_cmd
- `VAV-1` / `VAV_25A`: missing roles: zone_t
- `AVG-ZONE-TEMP` / `VAV_25A`: missing roles: zone_t
- `ZONE-COMFORT-PCT` / `VAV_25A`: missing roles: zone_t
- `FAULT-ELAPSED-HOURS` / `VAV_25A`: missing roles: zone_t

## Proxy / partial implementation

- Review registry `parity_status` and blockers for rules not yet oracle-aligned.
