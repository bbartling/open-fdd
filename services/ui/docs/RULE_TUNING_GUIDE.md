# Rule tuning guide

Sliders are defined in `configs/rule_defaults.yaml`. Each rule block maps to a `config_key` in `app/rules/__init__.py`.

## Workflow

1. Load data (BUILDING_100 or upload)
2. Map roles in **Role Mapping**
3. Adjust sliders in sidebar expanders
4. **Rule Tuning** tab → Run selected rules
5. Review **Fault Results** and **Trends**
6. Add engineer notes in sidebar text areas (included in export)

## Reset

Click **Reset sliders to defaults** in the sidebar.

## Confirm time

`confirm_minutes` × 60 → `confirm_seconds` passed to `confirm_fault()` (Open-FDD-style streak logic).

## Parameters by rule

| Rule | Key params |
| --- | --- |
| VAV-1 | `zone_low`, `zone_high`, `confirm_min` |
| AHU-SATDEV | `sat_dev_err`, `confirm_min` |
| ECON-2 | `econ2_oat_hi`, `econ2_damper`, `confirm_min` |
| OAT-METEO | `oat_err`, `confirm_min` (needs weather) |

Edit YAML to add new slider metadata — no code change required for min/max/step defaults.

## GL36 VAV-AHU AFDD variables (FC1–FC15)

The sidebar exposes the internal variables from ASHRAE Guideline 36-2018
Table 5.16.14.5 under each applicable FC rule. Defaults intentionally preserve
the app's prior behavior; slider labels state the GL36 reference default where
it differs. `confirm_min` is the passive-AFDD equivalent of `AlarmDelay`.

| GL36 variable | Sidebar key(s) | Rules |
| --- | --- | --- |
| ΔTSF — supply-fan temperature rise | `delta_supply_fan` | FC5, FC8, FC9, FC11, FC12, FC14, FC15 |
| ΔTmin — minimum OAT/RAT difference | `delta_t_min` | FC6 |
| εSAT | `eps_sat` | FC5, FC7–FC9, FC11–FC13 |
| εRAT | `eps_rat` | FC2, FC3 |
| εMAT | `eps_mat` | FC2, FC3, FC5, FC8, FC10, FC12 |
| εOAT | `eps_oat` | FC2, FC3, FC9–FC11 |
| εF — airflow/OA fraction error | `eps_airflow` | FC6 |
| εVFDSPD — VFD speed error | `eps_vfd_spd` | FC1 |
| εDSP — duct-static error | `eps_dsp` | FC1 |
| εCCET / εCCLT | `eps_ccet`, `eps_cclt` | FC14 |
| εHCET / εHCLT | `eps_hcet`, `eps_hclt` | FC15 |
| ΔOSmax — operating-state changes/hour | `delta_os_max` | FC4 |
| ModeDelay | `mode_delay_min` | FC1–FC15 |
| AlarmDelay | `confirm_min` | FC1–FC15 |

Operating-state boundaries are also tunable where used:
`fan_on_min`, `econ_min_pos`, `econ_full_open`, `clg_on_min`,
`clg_inactive_max`, `clg_full_min`, `htg_on_min`, and `htg_full_min`.

`TestModeDelay` belongs to the active functional-test sequence in Guideline 36.
Vibe19 performs passive historical AFDD and does not command an AHU into test
mode, so it is not represented as a fault-equation slider.

Legacy sliders (`mix_tol`, `supply_tol`, `sat_err`, `duct_static_err`,
`fan_hi`, `airflow_err`, `oat_rat_delta_min`) remain compatible. When changed,
the runner propagates them to the corresponding canonical GL36 variables unless
that specific canonical variable was also overridden.
