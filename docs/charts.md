---
title: Charts
nav_order: 7
---

# Charts: RCx and FDD

The **RCx** tab is a library of retro-commissioning views. Each view declares the roles it needs; the tab binds
them on the equipment in scope (see [Modeling](modeling.html)), draws the views that can, and lists the rest with
what they are missing. The **Charts** tab is a free-form history viewer for any tagged point, and the **FDD** tab
opens a per-rule plot.

Groups: air handlers (economizer, mixed/return/discharge temperatures, dampers, duct static, SAT reset, weekly
runtime), zones and VAV (comfort rank, temperatures, flows), plant (CHW, HW and CW temperatures and resets),
weather (BAS vs web outdoor air), sensors (health heatmap, sensor faults), metering and energy (demand, monthly
energy, degree-day baselines, M&V, EUI).

## The fault-lane convention

**Faults always show the same way: a 0/1 lane at the bottom of the plot**, with every time axis linked (tooltip
and zoom). Never draw faults as markers, shading or an extra series on the signal grid.

Code: wrap any ECharts option with `rcxWithFaultLane(option, lanes)` in `nf-app/static/rcx.js`:

```js
const option = rcxWithFaultLane(baseOption, [{ name: "ECON-1", data: [[ms, 0], [ms, 1] /* ... */] }]);
```

Several rules give several lanes. Fault data comes from the FDD hook's result points (tagged `fault`, `ruleRef`,
`equipRef`). Twelve views carry a lane today; the list is `fault_lanes` in `nf-app/rcx-parity.json`.

## Parity file

`nf-app/rcx-parity.json` maps every chart of the old 4.x central UI to where it lives now:

- `builders`: each old chart builder to a view id or function in the NF app;
- `presets`: the 18 RCx presets (zone comfort rank, zone temps, AHU DATs/MATs/RATs/dampers, duct static box,
  SAT/HW/CHW/CW reset scatters, VAV flows, fan speeds, meter vs CDD/HDD, ...);
- `fault_lanes`: views that draw a fault lane;
- `not_ported`: items intentionally dropped, each with a reason (for example utility bills and fuel prices, which NF does not hold).

`nf-app/tests/parity.test.mjs` fails if a builder or preset is missing, a view id is not registered, or a
`not_ported` entry has no reason. Adding a view means adding it to this file. See [Development](development.html#add-a-chart).

## Notes

- History is resampled by NF (`point/data ... &window=Ns&method=AVERAGE`), so big ranges stay small on the wire.
- Values are displayed in the chosen system (imperial or SI); see [Units](units.html).
- ECharts is vendored; the page makes no internet requests.
