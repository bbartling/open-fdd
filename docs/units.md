---
title: Units
nav_order: 4
---

# Units

FDD and analytics use SI. Supported measurements are converted on ingest; rules and stored results remain SI.
Imperial and other display choices are applied in the UI.

| Quantity | SI unit | Example input units |
|---|---|---|
| Temperature | °C | °F, K |
| Temperature difference | Δ°C | Δ°F, K |
| Pressure | Pa | kPa, inH2O, psi, bar |
| Air or water flow | L/s | m³/s, m³/h, cfm, gpm |
| Power / energy | kW / kWh | W, MW, Btu/h, Wh |
| Concentration | ppm | ppm |
| Relative humidity | %RH, 0–100 | % |
| Commands and positions | fraction, 0–1 | %, ratio, bool |
| Status | 0–1 | bool or numeric 0/1 |

Unknown or incompatible units are skipped. Open-FDD does not guess by value size: a unitless 0.5 command could mean
either a fraction or a percentage. Add the correct unit in NF. Sensor-validation sweeps also require the sensor unit
to match its SI quantity.

Conversion functions live in nf-app/static/units.js and are shared by the browser and FDD hook. The pandas tools use
the matching implementation in open_fdd/nf/units.py. See [Modeling](modeling.html).
