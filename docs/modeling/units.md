---
title: Unit contract
parent: Modeling
nav_order: 9
permalink: /modeling/units/
---

# Unit contract

Open-FDD stores and processes telemetry using the `metric-c-v2` SI ABI. Each point's source unit and quantity are declared by an engineer in the model/point map. The single Timescale telemetry writer converts supported source values once during ingest (and the one-time SI cutover normalizes existing samples); rule and analytics SQL consume the normalized value. Query-time source-unit admission is not part of the contract. A missing or incompatible declaration is marked `unit_undeclared` and excluded from unit-dependent assessment until resolved.

Parameter metadata declares both a semantic `kind` and an SI unit. Absolute temperatures are °C; temperature differences and rates use Δ°C and scale-only conversion; air pressure is Pa, hydronic pressure kPa, volumetric flow L/s, power kW, and interval energy kWh. Percent (0–100) and fraction (0–1) are separate kinds and are never inferred by magnitude. Status and occupancy mode remain boolean and enum/text values.

## Source conversion reference

These are source-to-storage conversions from `sql/contract/metric_units.json`. They run once at the writer boundary. The canonical factors in the contract should be consulted for precise conversions.

| Quantity | Canonical | Common declared source units |
| --- | --- | --- |
| Absolute temperature | °C | °F: `(value − 32) × 5/9`; °C: unchanged |
| Temperature difference / rate | Δ°C / Δ°C per hour | Δ°F: `value × 5/9` (no offset); Δ°C: unchanged |
| Air pressure | Pa | inH₂O: `value × 248.84`; Pa: unchanged |
| Hydronic pressure | kPa | psi: `value × 6.894757`; kPa: unchanged |
| Volumetric flow | L/s | cfm: `value × 0.471947`; gpm: `value × 0.0630902`; L/s: unchanged |
| Power | kW | W: `value × 0.001`; kBtu/h: `value × 0.29307107`; ton: `value × 3.5168525`; kW: unchanged |
| Interval energy | kWh | Wh: `value × 0.001`; kWh: unchanged |
| Percent / fraction | percent 0–100 / fraction 0–1 | Scale is explicit metadata; no magnitude heuristic |

## Display preference

Display preference is independent of the stored/processing ABI. APIs return SI values with unit metadata; the SPA may convert at presentation time to the user's chosen display units. Absolute temperatures use an offset; differences, rates, and other relative quantities use scale-only conversion. A display conversion never changes stored samples, SQL rule parameters, or the unit declared for a source point.

The contract source is [`metric_units.json`](../../sql/contract/metric_units.json); rule parameters declare kinds in [`sql/fdd/registry.yaml`](../../sql/fdd/registry.yaml). See [SI cutover ADR-012](../architecture/adr-012-si-processing-and-qualification.md).
