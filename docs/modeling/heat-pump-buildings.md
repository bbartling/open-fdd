---
title: Heat-pump buildings
parent: Haystack Modeling
nav_order: 4
---

# Water-source heat-pump buildings (agent guide)

Vendor-neutral documentation for agents packaging WSHP / geo-loop sites.
Do **not** invent missing trends. Do **not** copy AHU/VAV BUILDING_100 topology
onto these buildings.

## Canonical topology

```text
site → building
  ├── electric meter (serves building)
  ├── weather (web_oa_t; not BAS oa_t)
  └── source-water loop
        └── heatPump → serves controlled zone/space (1:1 default)
              └── heatPump → …
```

- Stamp units `equipType: heatPump`.
- Floor / Area A–D labels are **navigation** unless the BAS proves a shared
  thermal zone. Safer default: one controlled space per unit.
- Do **not** model WSHPs as VAV boxes.
- Do **not** stamp a geo/source-water loop as `chwPlant` merely to light CHW
  analytics. Loop semantics are distinct (product type support for a dedicated
  loop family may still be incomplete — document loop points honestly and avoid
  mislabeling).

## Role tiers

Declare unit + provenance. Mark UNAVAILABLE when the BAS export lacks the point.

1. **Identity / topology** — site/building/equip refs, `equipType`, zone/space,
   loop membership, display name.
2. **Minimum screening** — `zone_t`, `sat` (DAT), fan command **or** fan status
   with explicit semantics.
3. **Operating state** — compressor status/cmd, heating call, cooling call,
   actual mode, reversing-valve status, occupancy.
4. **Control** — heating/cooling (and SAT) setpoints, alarms/lockout.
5. **Water side** — per-unit EWT/LWT; shared loop supply/return, DP, pumps.
6. **Energy** — unit kW/amps; building interval kW / kWh.

## Anti-patterns

- Never infer compressor operation from fan status.
- Never infer heating vs cooling solely from DAT without labeling the result as
  **screening / inference**.
- Never synthesize constant fake compressor/mode/setpoint columns to “green”
  Overview.
- Never treat fan status as interchangeable with fan command for rules that
  still require `fan_cmd` in SQL (see [rule readiness](rule-readiness.html)).
- Site/vendor identifiers stay in the preprocess package, never in product Rust.

## Compact map example

```json
{
  "equipType": "heatPump",
  "equip": "HP_1",
  "points": {
    "discharge-air-temp": "SupplyAirTemp",
    "zone-air-temp": "ZoneTemp",
    "fan-status": "SupplyFanStatus"
  }
}
```

If compressor / mode / setpoints / EWT are absent from the export, leave them
unmapped and produce a BAS re-export request in the **site** workspace — not
fake CSV columns.
