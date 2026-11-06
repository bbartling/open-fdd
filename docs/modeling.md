---
title: Modeling
nav_order: 4
---

# Model your site in NF

Open-FDD has no configuration of its own. Sites, equipment, points and units are **discovered** from NF's Haystack
model. To support a new building, tag it in NF (console, or the NF MCP `tag_points` / `manage_equipment`); no app
change is needed, and the app must never be forked per site.

## What to tag

| Level | What NF needs |
|---|---|
| **Site** | a site record with `latitude`, `longitude`, timezone, and optionally `area` (floor area) |
| **Equipment** | an equip instance with markers that say what it is (`ahu`, `vav`, `chiller`, `boiler`, `meter`, ...) |
| **Points** | `siteRef`, `equipRef` (and `deviceRef` for the BACnet device), `class`, `markers`, `kind`, `unit` |

Trend (history) every point you want to chart or run rules on.

- **Site coordinates** drive the weather hook (Open-Meteo). Set them in NF Sites.
- **Site area** is the `area` attribute on the NF site record. It is assumed to be ft2 unless the site has
  `areaUnit` set to m2. Without it, energy charts show kWh instead of EUI (kWh/m2/yr, shown as kBtu/ft2/yr in the imperial display).
- **Units**: set `unit` on the point (`degF`, `cfm`, `inH2O`, ...). Open-FDD converts to SI on ingest. See [Units](units.html).

## How roles bind

Each rule and chart declares **roles**, the inputs it needs (for example `sat`, `sat_sp`, `fan_cmd`, `zone_t`).
The catalog `nf-app/static/fdd-catalog.json` lists every role with the NF classes and Haystack markers that fill it.
A point fills a role when:

1. its NF **class** is in the role's class list (preferred, best match), or
2. it carries **every marker** of the role.

Equipment kinds (ahu, vav, chiller, ...) come from the equip's own markers. Weather-service points (marker
`weather`) fill only `web_*` roles; equipment sensors never do. The same binding code runs in the browser and in the
FDD hook, so the UI and the hook cannot disagree.

NF class names are dash-case, for example `discharge-air-temp-sensor`, `zone-air-temp-sensor`, `outside-damper-cmd`.
The full list is in NF at `GET /api/v1/equipment/classes?pageSize=1000`.

## The FDD tab: "missing inputs"

The FDD tab lists every rule per equipment with a status:

- **can run now**: all required roles are bound.
- **missing inputs**: shows the missing roles (for example `needs sat_sp`). Add the class or markers to a point in
  NF, reload, and the rule becomes runnable.

The RCx tab does the same for charts: views that cannot draw are listed with what they are missing.
Browse the rules and their roles in [FDD rules](fdd-rules.html).

## Tips

- Prefer an NF **class** over bare markers; it is unambiguous.
- Tag spare or unused I/O so it is not mistaken for a sensor.
- One equip instance per physical unit; give every point an `equipRef` and `siteRef`.
- Check the Model and RDF tab for dangling references ([RDF and SPARQL](rdf-sparql.html)).
- How NF stores these tags (layers, one marker per query clause, markers are not derived from `class`) and how to
  check a site from a terminal: [Haystack tagging](operations/nf/haystack-tagging.html).
