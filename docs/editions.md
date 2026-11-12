---
title: Lite vs Full
nav_order: 3
has_children: true
---

# Lite vs Full

Open-FDD ships two NF apps from one shared source. Pick the edition from the host, not from the building. Both read the same Haystack
model in NF ([data model](modeling.html)); they differ in whether a rule engine runs on the box.

| | **Lite** | **Full** |
|---|---|---|
| NF app id | `open-fdd-lite` | `open-fdd` |
| Source | [`lite/`](https://github.com/bbartling/open-fdd/tree/master/lite) | [`nf-app/`](https://github.com/bbartling/open-fdd/tree/master/nf-app) |
| Host | 1 GB, Raspberry Pi class | 2 GB or more; 4 GB or more is comfortable |
| FDD engine | none | SQLite (about 2 GB), PGlite (4 GB or more) or TimescaleDB |
| Includes | dashboard, charts, points, NF BACnet server view, CSV export, RDF export, weather hook | Lite plus FDD and RCx tabs, fault points, SQL rules, SPARQL hook |
| Scheduled hooks | `weather` every 20 min | `fdd` hourly, `weather` every 20 min, `sparql` on request |
| History it sees | NF's own, about 7 days | NF's, or long-range history from Timescale |
| Weather BACnet mirror | on by default | off by default |

Both write only their own result points and weather variables. Neither writes to field devices or adds a second historian.

## Use Lite when

- the host has about 1 GB of RAM (NF alone uses most of it);
- you only need live values, a week of trends, the model as Turtle and the BACnet server view;
- FDD runs elsewhere and you want a light local dashboard.

## Use Full when

- the host has 2 GB or more and you want faults, RCx charts and fault points in NF;
- you need history longer than NF's week: enable NF's TimescaleDB connector and set the app option `timescale`. Rules then run in the database.
  See [`nf-app/timescale`](https://github.com/bbartling/open-fdd/tree/master/nf-app/timescale).

## Rules of thumb

- Build, test and install from a PC, never on the small box. See [Normal Framework](normal-framework.html).
- Do not run both editions on one NF. Both ship a weather hook that writes the same variables.
- A small host that gets heavier work later is a reason to replace the host, not to squeeze Full onto it.

## Charts and export

Both editions include [Charts and export](charts.html).
