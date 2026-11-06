---
title: Lite or full
parent: NF operations
nav_order: 1
---

# Lite or full?

Pick the edition from the host, not from the building. Both read the same Haystack model in NF and need the same
tagging ([Haystack tagging](haystack-tagging.html)); they differ in whether a rule engine runs on the box.

| | **Lite** ([`lite/`](https://github.com/bbartling/open-fdd/tree/master/lite)) | **Full** ([`nf-app/`](https://github.com/bbartling/open-fdd/tree/master/nf-app)) |
|---|---|---|
| NF app id | `open-fdd-lite` | `open-fdd` |
| Host | 1 GB boxes, Raspberry Pi class | 2 GB or more; 4 GB or more is comfortable |
| FDD engine | **none** (no rules run) | SQLite-WASM (about 2 GB), PGlite (4 GB or more), or TimescaleDB |
| What you get | dashboard, charts, points, view of NF's BACnet server, RDF export, weather hook | everything in Lite plus the FDD and RCx tabs, fault points, SPARQL |
| History it can see | NF's own history: **about 7 days** kept in NF's Redis time series (resampled by NF) | the same, or long-range history from TimescaleDB |
| Hook dependencies | none (Node built-ins) | sql.js, PGlite, `pg` |

## Choose Lite when

- the host is a Raspberry Pi 3 or any box with about 1 GB of RAM. NF itself already uses most of it (its many service
  processes sit around 400 to 450 MB), so there is no room for a rule engine;
- you only need to look: live values, a week of trends, the model as Turtle, the BACnet server view;
- you run FDD somewhere else (a PC or server reading NF's API) and want only a light local dashboard.

## Choose full when

- the box has at least 2 GB (SQLite engine) or 4 GB (PGlite) and you want faults, RCx charts and fault points in NF;
- you need history longer than NF's week. Enable NF's **TimescaleDB northbound connector** and set the hook's
  `timescale` config: the rules then run inside the database, results and long-range history stay there, and a
  size cap (default **100 GB**, oldest chunks dropped first) keeps the disk bounded. Details and setup in
  [`nf-app/timescale/README.md`](https://github.com/bbartling/open-fdd/blob/master/nf-app/timescale/README.md).
  Use this on larger hosts, not on a Pi.

## Rules of thumb

- Never build, test or run heavy things on a small box; deploy from a PC ([Install](../../install.html)).
- Do not run both editions on one NF unless you mean to: both ship a weather hook that writes the same
  labels (`oa_dry_bulb_web`, ...), so two writers would likely fight. Move a box from one to the other and retire the old
  app (see [Lite](../../lite.html)).
- A small host that gets heavier work later (real equipment, more points, longer history) is a reason to replace the
  host, not to squeeze the full app onto it. Check power first on a Pi: undervoltage looks like random
  restarts (`vcgencmd get_throttled`).
