---
title: RCx & FDD plot examples
parent: Web App
nav_order: 5
permalink: /web-app/rcx-plots-by-hvac.html
---

# RCx plots out of the box (by HVAC system type)

**UI:** **RCx Plots** (`/rcx`) — Plotly presets. Overview is **tables + health matrices only** (no Plotly on Overview); motor / economizer / BAS figures live here as additive presets.

**Sources of truth:** [`services/central/src/analytics/rcx_presets.rs`](../../services/central/src/analytics/rcx_presets.rs) (`RCX_PRESETS`) · [`frontend/web/src/nav/rcxCatalog.ts`](../../frontend/web/src/nav/rcxCatalog.ts) (`REQUIRED_RCX_PRESET_IDS`, `RCX_FAMILY_ORDER`) · overview-analytics loaders in [`frontend/web/src/api/rcxOverviewPresets.ts`](../../frontend/web/src/api/rcxOverviewPresets.ts).

Do **not** drop any `REQUIRED_RCX_PRESET_IDS` id. Heat pump / Weather family pickers may show empty placeholders until presets exist for that site.

API: `GET /api/analytics/rcx/presets` · `POST /api/analytics/rcx/preset`.


## Example screenshots (GH Pages)

Operator exports from the product UI — illustrative only. Empty series still mean missing roles, not a broken plot engine.

### RCx Plots

| Family | Example |
|--------|---------|
| Zones / VAV — comfort rank | ![zone comfort rank]({{ site.baseurl }}/assets/plot-examples/rcx_Zones_VAV_zone_comfort_rank.png) |
| Zones / VAV — zone temps | ![zone temps]({{ site.baseurl }}/assets/plot-examples/rcx_Zones_VAV_zone_temps.png) |
| Zones — worst zones companion | ![worst zones]({{ site.baseurl }}/assets/plot-examples/rcx_worst_zones.png) |
| AHU — SAT vs web OAT | ![SAT reset]({{ site.baseurl }}/assets/plot-examples/rcx_AHU_air_ahu_sat_reset_scatter.png) |
| AHU — duct static box | ![duct static]({{ site.baseurl }}/assets/plot-examples/rcx_AHU_air_duct_static_box.png) |
| AHU — motor weekly | ![motor weekly]({{ site.baseurl }}/assets/plot-examples/rcx_AHU_air_ahu_motor_weekly.png) |
| AHU — economizer delta | ![econ delta]({{ site.baseurl }}/assets/plot-examples/rcx_AHU_air_economizer_delta.png) |
| AHU — economizer MAT residual | ![econ mat]({{ site.baseurl }}/assets/plot-examples/rcx_AHU_air_economizer_mat_resid.png) |
| AHU — economizer temps + OA damper | ![econ temps]({{ site.baseurl }}/assets/plot-examples/rcx_AHU_air_economizer_temps_overlay.png) |
| Boiler / HW — HWS vs OAT | ![HW reset]({{ site.baseurl }}/assets/plot-examples/rcx_Boiler_HW_hw_reset_scatter.png) |
| Chiller — CHWS vs OAT | ![CHW reset]({{ site.baseurl }}/assets/plot-examples/rcx_Chiller_CHW_tower_chw_reset_scatter.png) |
| Chiller — CHW temps | ![CHW temps]({{ site.baseurl }}/assets/plot-examples/rcx_Chiller_CHW_tower_chw_temps_ts.png) |
| Mech cooling OAT bins | ![mech bins]({{ site.baseurl }}/assets/plot-examples/rcx_Chiller_CHW_tower_mech_cooling_oat_bins.png) |
| Weather — BAS vs web OAT | ![bas vs web]({{ site.baseurl }}/assets/plot-examples/rcx_Weather_bas_vs_web_oat.png) |

### FDD Plots

| Rule | Example |
|------|---------|
| FC1 — duct static | ![FC1]({{ site.baseurl }}/assets/plot-examples/fdd_FC1_series.png) |
| ECON-4 — low OA fraction | ![ECON-4]({{ site.baseurl }}/assets/plot-examples/fdd_ECON-4_series.png) |

---

## Family → presets (equipment kinds)

Kinds are the preset’s `eq_kinds` filter (package stamp / id heuristics). Empty series when roles are missing — not a silent invent.

### Zones / VAV (`VAV`, zone equipment)

| Preset id | Chart | What you see |
|-----------|-------|----------------|
| `zone_comfort_rank` | ranking | Occupied comfort-fail ranking |
| `zone_temps` | timeseries | Space temps |
| `vav_flows` | timeseries | VAV airflow |
| `vav_health_matrix` | vav_health | Broken / comfort / rogue donut + worst bars |

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
| **Overview** | Health matrices per family (AHU temp/pressure/econ, chiller, tower, HP, PID, sensors, zone-other) |
| **FDD Plots** (`/reports`) | Per-equipment FDD/fault-oriented Plotly |
| **Inspect** (`/inspect`) | CSV / historian column overlay timeseries |

## Honesty

Presets with missing roles return empty figures / warnings — never zero-fill. Site without that HVAC type simply has no series for those `eq_kinds`.
