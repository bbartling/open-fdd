---
title: Default tolerances and G36
parent: Rules
nav_order: 8
---

# Default tolerances and G36

Open-FDD's shipped tolerances are starting values. This page compares them with the published SI values in ASHRAE
Guideline 36-2018 (Tables 5.16.14.5 multi-zone VAV and 5.18.13.5 single-zone VAV, with
[Addendum u, 2021](https://www.ashrae.org/file%20library/technical%20resources/standards%20and%20guidelines/standards%20addenda/g36_2018_u_20210330.pdf)).
It is an audit, not a G36 compliance claim. 5.0.21 changes no default; behavior changes are tracked in #1763.

## AHU fault-equation tolerances (multi-sensor equations)

| Parameter | Rules | Current default | G36-2018 SI | Status |
|---|---|---|---|---|
| SAT / RAT sensor error | FC2–FC12 `eps_sat`, `eps_rat` | 0.639 °C | 1 °C | Differs (current = 1.15 °F) |
| MAT sensor error | FC2, FC3, FC5, FC8, FC10, FC12 `eps_mat` | 0.639 °C | 3 °C | Differs |
| OAT sensor error | FC2, FC3, FC9–FC11 `eps_oat` | 0.639 °C | 1 °C local, 3 °C shared | Differs; needs placement metadata |
| Supply-fan temperature rise | FC5, FC8, FC9, FC11, FC12 `delta_supply_fan` | 0.306 °C | 1 °C multi-zone, 0.5 °C single-zone | Differs |
| Minimum \|OAT − RAT\| | FC6 `oat_rat_delta_min` | 2.78 °C | 6 °C | Differs |
| Airflow error | FC6 `eps_airflow` | 0.15 | 0.30 | Differs |
| VFD speed error | FC1 `eps_vfd_spd` | 0.13 | 0.05 | Differs (label corrected in 5.0.21) |
| Duct-static error | FC1 `eps_dsp` | 29.86 Pa | 25 Pa | Differs (current = 0.12 inH2O) |
| Operating-state changes | FC4 `delta_os_max` | 5 per hour | 7 in a trailing 60 min | Differs |
| Design minimum OA airflow | FC6 `min_flow_design` | 2359.7 L/s | Site-specific | Not a G36 constant; set per AHU |

G36 also gives 30 min mode-change suppression, 30 min alarm persistence and 120 min commissioning expiry. These are
three separate functions; their mapping to Open-FDD timers is tracked with #1758 and the one-timer contract.

## Sensor-validation starters (engineering proposals, not G36)

| Check | Current | Proposed starter (#1763) |
|---|---|---|
| Range confirm | per rule | 5 min |
| Flatline window / span | 1 h, 0.0556 °C | 1 h; 0.1 °C temperature, 0.5 %RH humidity |
| Missing data | SV-STALE gap rules | max(30 min, 3 expected intervals); COV-only data is not a fault by absence |
| Spike, unknown quantity | none | 25 % of declared rated span, adjacent samples ≤ 10 min apart |
| Rate per hour | role-specific | stays role-specific; unknown context is unassessed |

Sensor-error allowances belong in the multi-sensor equations above. They are not flatline tolerances, sensor
validity bands or setpoints. A constant reading can be legitimate (a well-controlled loop or idle equipment), so
flatline is a suspected-stuck indication only.

## Known label and default issues

- FC1 `eps_vfd_spd` was labelled "GL36 default 5 %" with a 0.13 default. The label is corrected; the value is unchanged.
- FC7 `htg_full_min` and the pandas `clg_full_min` were labelled "GL36 99 %". Labels corrected. `clg_full_min`
  defaults to 0.01, below its own 0.5 minimum; fixing that changes behavior and is deferred to #1763.

Saved site, equipment and sensor tuning is never changed by a release.
