---
title: Units
nav_order: 8
---

# Units

**FDD and analytics math run in SI only.** NF points arrive in whatever unit the site uses (often US customary);
the UI shows the user's display system.

| Step | Where | Function (`nf-app/static/units.js`, global `ofddUnits`) |
|---|---|---|
| Ingest | FDD hook, charts, export | `toSI(value, unit)` returns `{ value, unit, quantity }`, or `null` for an unknown unit |
| Display | UI | `fromSI(value, siUnit, system)` where system is `"imperial"` or `"si"` |
| Differences | UI | `deltaFromSI(d, siUnit, system)`: temperature deltas, no 32-degree offset |

The one file works as a classic browser script and as CommonJS in the FDD hook.

## Canonical SI units

| Quantity | SI unit | Accepted inputs (examples) |
|---|---|---|
| temperature | °C | °F, K |
| pressure | Pa | kPa, inH2O, psi, bar |
| air / water flow | L/s | m3/s, m3/h, cfm, gpm |
| power | kW | W, MW, Btu/h, ton, hp |
| energy | kWh | Wh, MWh, kBtu, MMBtu, therm |
| percent | % (0-100) | %RH, pct |
| concentration | ppm | |

Unit names are matched loosely (case, spaces and underscores ignored). The authoritative table is `units.js`.

## The display toggle

A header toggle switches imperial / SI and stores the choice in `localStorage["openfdd-units"]` (default imperial for
US sites). Chart pages in other windows follow the toggle. The CSV export lets you pick display or stored units
([Export](export.html)).

## Rules

- Never convert inside a rule: rules and thresholds are SI. The rule defaults in [FDD rules](fdd-rules.html) are SI.
- A point with an unknown `unit` is not converted; fix the `unit` tag in NF ([Modeling](modeling.html)).
- Temperature differences use `deltaFromSI`, never `fromSI`.
