---
title: RCx plots by HVAC type
nav_order: 25
---

# RCx plots out of the box (by HVAC system type)

**UI:** **RCx Plots** (`/rcx`) — Plotly presets. Overview is **tables + health matrices only** (no Plotly on Overview); motor / economizer / BAS figures live here as additive presets.

**Sources of truth:** [`services/central/src/analytics/rcx_presets.rs`](../services/central/src/analytics/rcx_presets.rs) (`RCX_PRESETS`) · [`frontend/web/src/nav/rcxCatalog.ts`](../frontend/web/src/nav/rcxCatalog.ts) (`REQUIRED_RCX_PRESET_IDS`, `RCX_FAMILY_ORDER`) · overview-analytics loaders in [`frontend/web/src/api/rcxOverviewPresets.ts`](../frontend/web/src/api/rcxOverviewPresets.ts).

Do **not** drop any `REQUIRED_RCX_PRESET_IDS` id. Heat pump / Weather family pickers may show empty placeholders until presets exist for that site.

API: `GET /api/analytics/rcx/presets` · `POST /api/analytics/rcx/preset`.

## Family → presets (equipment kinds)

Kinds are the preset’s `eq_kinds` filter (package stamp / id heuristics). Empty series when roles are missing — not a silent invent.

### Zones / VAV (`VAV`, zone equipment)

| Preset id | Chart | What you see |
|-----------|-------|----------------|
| `zone_comfort_rank` | ranking | Occupied comfort-fail ranking |
| `zone_temps` | timeseries | Space temps |
| `vav_flows` | timeseries | VAV airflow |
| `vav_health_matrix` | ranking | Broken / comfort / rogue style ranking |

### AHU / air (`AHU`, `RTU`, `MAU`)

| Preset id | Chart | What you see |
|-----------|-------|----------------|
| `ahu_dats` | timeseries | DAT / SAT |
| `ahu_mats` | timeseries | MAT |
| `ahu_rats` | timeseries | RAT |
| `ahu_dampers` | timeseries | OA damper % |
| `ahu_cooling_valves` | timeseries | Cooling valve % |
| `ahu_heating_valves` | timeseries | Heating valve % |
| `fan_speeds` | timeseries | Fan speed / cmd |
| `duct_static_box` | box | Duct static (fan-on) |
| `duct_static_ts` | timeseries | Duct static + setpoint |
| `ahu_sat_reset_scatter` | scatter vs OAT | SAT vs web dry-bulb |
| `ahu_motor_weekly` | overview analytics | Weekly supply-fan / motor hours |
| `economizer_delta` | overview analytics | Free-cooling delta scatter (fan-on) |
| `economizer_mat_resid` | overview analytics | MAT residual vs ideal mixing |
| `economizer_temps_overlay` | overview analytics | Free-cooling temps + OA damper |

Frozen **required** AHU ids include the timeseries/box/scatter set above (not every economizer/motor additive id is in the frozen 18 — additives must still stay listed in catalog loaders).

### Boiler / HW (`BOILER`)

| Preset id | Chart | What you see |
|-----------|-------|----------------|
| `hw_reset_scatter` | scatter vs OAT | HWS vs web dry-bulb |
| `boiler_motor_weekly` | overview analytics | Weekly HW pump motor hours |

### Chiller / CHW / tower (`CHILLER`, `CHW`, `TOWER`, `CT`)

| Preset id | Chart | What you see |
|-----------|-------|----------------|
| `chw_reset_scatter` | scatter vs OAT | CHWS vs web dry-bulb |
| `cw_reset_scatter` | scatter vs wet-bulb | CW leave temp vs wet-bulb (+ dry-bulb ref) |
| `chw_temps_ts` | timeseries | CHW supply / return / ΔT |
| `cw_temps_ts` | timeseries | CW supply / return / ΔT |
| `chiller_motor_weekly` | overview analytics | Weekly plant motor hours |
| `mech_cooling_oat_bins` | overview analytics | Mech cooling hours by OAT bin (`CHILLER` / `AHU` / `HP`) |

### Metering (`METER`, plus plant kinds for fuel context)

| Preset id | Chart | What you see |
|-----------|-------|----------------|
| `meter_elec_cdd` | metering | Electric kWh/month vs CDD |
| `meter_gas_hdd` | metering | Gas/month vs HDD |

### Weather

| Preset id | Chart | What you see |
|-----------|-------|----------------|
| `bas_vs_web_oat` | overview analytics | BAS vs web outdoor-air temperature (`WEATHER` / `AHU`) |

### Heat pump

Family picker placeholder in the SPA. Dedicated HP RCx presets are **not** a separate catalog block yet — HP may appear on shared presets (e.g. `mech_cooling_oat_bins`). Overview still has a **Heat-pump health** matrix (rules), which is FDD — not RCx Plotly.

### Zone Other / MQTT generic zone

No dedicated RCx preset family. Covered on **Overview** via **Generic zone monitoring** health matrix (`zone_other`), not RCx Plots.

## Related (not RCx Plots)

| Surface | Role |
|---------|------|
| **Overview** | Health matrices per family (AHU temp/pressure/econ, chiller, tower, HP, PID, sensors, zone-other) — see [`OVERVIEW_HEALTH_API.md`](OVERVIEW_HEALTH_API.md) |
| **FDD Plots** (`/reports`) | Per-equipment FDD/fault-oriented Plotly |
| **Inspect** (`/inspect`) | CSV / historian column overlay timeseries |

## Honesty

Presets with missing roles return empty figures / warnings — never zero-fill. Site without that HVAC type simply has no series for those `eq_kinds`.
