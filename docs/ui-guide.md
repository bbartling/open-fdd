---
title: UI guide
parent: DuckDB vs Timescale
nav_order: 2
---

# UI guide

The UI is plain JavaScript in the NF plugin. The Timescale install is `nf-app/static/`; the DuckDB install is `lite/static/`. Charts use Apache ECharts 6.1.0, vendored in the app (`nf-app/static/vendor/echarts.esm.min.js`, DuckDB install `lite/static/vendor/echarts.min.js`).

Developers: UI API contract 1.0.0 ([#1807](https://github.com/bbartling/open-fdd/issues/1807), [OpenAPI](https://github.com/bbartling/open-fdd/blob/master/openapi/open-fdd-ui-api.yaml)). The reference mock and the contract suite are in [`contract/`](https://github.com/bbartling/open-fdd/tree/master/contract).

## Pages

| Page | Edition | What it shows |
|---|---|---|
| `index.html` | both | The dashboard. The top bar is the site, the live clock, theme, and (Timescale install) the display-unit toggle. |
| `chart.html` | both | One catalog chart in its own window (`?c=`, site, optional equip, hours, point). |
| `tree.html` | both | Read-only BACnet object list beside the Haystack tree (ECharts graph). |

## Tabs

The DuckDB install shows Overview, Charts, Backend server, and Model/RDF. The Timescale install adds Analytics, Fault detection and Export, and puts the retro-commissioning panels on Overview.

| Tab | Shows | Charts |
|---|---|---|
| Overview | Site summary. Sensor and process points for one equipment: live cards, status chips, I/O table, point table, history. Fault and timeline points stay on Fault detection. The Timescale install also shows the weekly occupancy editor with its occupied zone temperature range slider and the retro-commissioning panels below. | History is a time-series line (step for Bool). Retro-commissioning types are in the next table. |
| Charts | One catalog chart at a time. | See the catalog table. |
| Analytics | Timescale install. Scatter, air-handler timeseries, VAV plots and energy. History loads when the tab opens. | See the catalog table. |
| Fault detection | Timescale install. Fault / pass / skipped / insufficient chips, one open rule (SI thresholds, inputs, tune drawer), and a More section (fault heat map, fault charts, rule-input table). | Open rule: time-series lines, red shade for a confirmed fault, grey shade for equipment off, 0/1 fault lane. Heat map of fault hours. |
| Backend server | Local BACnet objects, present value versus the Haystack point, property cards. | None. |
| Export | Timescale install. One CSV of one equipment's I/O and fault columns. | None. See [Charts and export](charts.html#export). |
| Model/RDF | Haystack tree, model checks, Turtle and model JSON download, and a SPARQL panel (SELECT, ASK, CONSTRUCT, DESCRIBE). Fault and timeline points stay in the Turtle and out of the tree. The panel posts the query to the `sparql` hook; Oxigraph runs in the NF Node process. | The tree is an ECharts graph. |

## Chart catalog

Both editions. Defined in `charts.js`.

| Id | Title | ECharts series |
|---|---|---|
| `temps` | Temperatures | line, time axis |
| `heatmap` | Hour-of-day heatmap | heatmap |
| `daily` | Daily min / mean / max | candlestick used as a range bar |
| `runtime` | Equipment runtime | bar (hours on) |
| `psy` | Outdoor air: temp vs humidity | scatter |
| `other` | All signals | line per unit, step line for on/off |

## RCx and FDD views

Registered with `rcxView` in `nf-app/static/`. A panel is omitted when the model has no equipment for it. `tabHidden` views stay in the registry and are not drawn on the tab. Faults, when the view has them, are a 0/1 step line at the bottom (`rcxWithFaultLane`).

| Id | Title | Series | Where |
|---|---|---|---|
| `weekly-fan`, `weekly-fan-cmd` | Weekly runtime: AHU supply fans | bar | Overview |
| `weekly-pump` | Weekly runtime: Pumps | bar | Overview |
| `weekly-chw-pump`, `weekly-chw-pump-cmd` | Weekly runtime: Chilled-water pumps | bar | Overview |
| `weekly-cw-pump` | Weekly runtime: Condenser-water pumps | bar | Overview |
| `weekly-compressor` | Weekly runtime: Compressors | bar | Overview |
| `weekly-chiller`, `weekly-chiller-cmd` | Weekly runtime: Chillers | bar | Overview |
| `weekly-tower-fan` | Weekly runtime: Cooling-tower fans | bar | Overview |
| `ahu-runtime-daily` | AHU supply fans: run hours per day | bar | hidden |
| `runtime-daily-pump`, `runtime-daily-chw-pump`, `runtime-daily-cw-pump`, `runtime-daily-compressor`, `runtime-daily-chiller`, `runtime-daily-tower-fan` | That motor: run hours per day | bar | hidden |
| `mech-cooling-hours` | Mechanical cooling hours by outdoor air | stacked bar | Overview |
| `mech-cooling-compressor-status`, `mech-cooling-chiller-status`, `mech-cooling-chiller-cmd` | Mechanical cooling hours by outdoor air (one signal) | stacked bar | hidden |
| `economizer-delta` | Economizer: free-cooling delta scatter | scatter | Overview |
| `economizer-mat-residual` | Economizer: MAT residual | line, fault lane | Overview |
| `economizer-temps` | Economizer: temperatures and OA damper | line, fault lane | Overview |
| `ahu_dats`, `ahu_mats`, `ahu_rats`, `ahu_dampers`, `fan_speeds`, `duct_static_ts` | AHU timeseries (DAT, MAT, RAT, damper, fan, duct static) | line | Overview |
| `duct_static_box` | AHU — duct static, fan on | boxplot | Overview |
| `chw_temps_ts`, `cw_temps_ts` | CHW and condenser-water temperatures | line | Overview |
| `zone_comfort_rank` | Zones — comfort ranking | bar and pie | Overview |
| `zone_temps` | Zones — space temps, 10th–90th band | line | Overview |
| `vav_health` | VAV — health | bar and pie | Overview |
| `vav_positions`, `vav_reheat_dats` | VAV damper, reheat valve, discharge temp | line | Overview |
| `meter_elec_cdd`, `meter_gas_hdd` | Monthly energy vs degree days | scatter and bar | Overview |
| `energy-demand-heatmap` | Interval demand heatmap | heatmap | Overview, per meter |
| `energy-interval-demand` | Interval demand | line | Overview |
| `energy-monthly` | Monthly energy | line | Overview |
| `energy-weather-scatter` | Energy vs degree days | scatter and bar | Overview |
| `energy-demand-peak` | Monthly peak kW vs kWh | bar and line | Overview |
| `energy-peak-cooling` | Peak demand, cooling days vs other days | bar | Overview |
| `energy-mv` | M&V baseline vs reporting | scatter and line | Overview |
| `energy-peer-bullet`, `energy-peer-bars`, `energy-ranked-eui` | Site EUI vs peers | bar | Overview |
| `energy-rolling12` | Rolling 12-month EUI | line | Overview |
| `energy-intensity-heatmap` | Intensity heatmap (site × month) | heatmap | Overview |
| `energy-stacked-meters` | Stacked monthly energy by meter | stacked bar | Overview |
| `bas-vs-web-oat` | BAS vs web outdoor-air temperature | line, band, fault lane | Fault detection |
| `bas-vs-web-oat-hist` | BAS vs web outdoor-air deviation | bar | hidden |
| `fdd-sensor-fault` | Sensor with the most sweep faults | heatmap | Fault detection |

kWh twins of the meter views use the same id with `-kwh`. Backends and export limits are on [DuckDB vs Timescale](editions.html).

## Occupied zone temperature range

The Overview shows a two-handle slider beside the weekly occupancy calendar. It sets the temperature band the site's occupied zones should hold.

| | |
|---|---|
| Limits | 65-80 F (18.333-26.667 C). Values are clamped; never negative. |
| Default | 70-75 F (21.111-23.889 C), used when nothing valid is saved. |
| Minimum gap | 2 F (1.111 K). The handles stop that far apart, and the server enforces the same gap. |
| Units | Stored in degC. Shown in the unit system of the SI/imperial button; imperial is display only and never stored. |
| Saved where | In the site's occupancy calendar document (`OCC-CALENDAR`, field `zone_band: {lo_c, hi_c}`), so it is per site, revisioned, and rolled back or reset with the calendar. The save needs the Timescale store, like the rest of the calendar. |
| Rejected | A saved or posted band that is missing, non-numeric, NaN or inverted (low above high) is refused and nothing is stored. An unusable stored band reads as the 70-75 F default. |

What it changes, on both the DuckDB and Timescale engines:

- Zone comfort analytics: the `{lo}` / `{hi}` of `sql/analytics/zone_comfort.sql` and the comfort band on the zone comfort charts (a zone's own setpoint band still wins on the chart).
- Zone comfort FDD rules: VAV-1 `ZONE_T_LO` / `ZONE_T_HI` and SCHED-1 `comfort_low` / `comfort_high`. A run records the band it used in the result's `parameters.zone_band` (the values applied, any rule value left alone, and the calendar revision).

Precedence, lowest to highest: shipped default (70-75 F) < the site's saved band < site rule tuning < equipment rule tuning. An explicit per-rule tuning value always wins over the band; if only one end of a pair is tuned, the band supplies the other end only while the gap stays at least 2 F.
