---
title: Lite
nav_order: 3
---

# Open-FDD Lite

The small-box edition (formerly "Bench Viz"): a tag-driven dashboard, charts, a view of NF's BACnet server,
RDF export and a weather hook. **No FDD engine and no npm dependencies.** Built for 1 GB machines such as a
Raspberry Pi 3. NF app id `open-fdd-lite`; source in
[`lite/`](https://github.com/bbartling/open-fdd/tree/master/lite).

## What you get

- Tabs: Overview, Charts, Points, BACnet Server, Model and RDF. Site and equipment pickers; the tab is kept in the URL hash.
- Everything is rendered from NF's Haystack model. To support a new site, tag its points in NF.
- Weather hook (every 20 minutes): Open-Meteo for the site's latitude/longitude (read from NF) into three global
  variables and three analog values on NF's BACnet server (`WEB OA-T`, `WEB OA-H`, `WEB OA-DP`).
- Same light "blueprint" / dark themes as the full edition.

## Deploy

```bash
python3 scripts/nf/hooks/nf_app_sync.py --env <console env> push lite/app.json
```

The page is then at `/api/v1/apps/static/open-fdd-lite/`. Other actions: `status`, `run`, `diff`, `pull`.
The manifest asks for API-key scopes (`normalgw.hpl.v1/v2.readwrite`, `normalgw.bacnet.v1/v2.readwrite`,
`normalgw.ontology.v1.readonly`), which only matter once NF's own login is enabled.

## Weather hook settings

| key | default | meaning |
|---|---|---|
| `site` | `""` | NF site id; only needed when several sites have coordinates |
| `bacnetMirror` | on in Lite (the edition default) | app option; `false` skips the BACnet objects (alias `bacnet_mirror`) |
| `avInstances` | `[1, 2, 3]` | AV instance numbers for temperature, RH, dewpoint |

Set the site coordinates in NF (Sites), not in code. The hook never tags points: tag the weather variables in NF
(`weather` marker plus a `weatherStationRef`) for them to appear on the dashboard.

{: .warning }
Never pass an existing point uuid to `POST /api/v1/bacnet/local`: it overwrites that point.

## Lite or full?

| | Lite | Full |
|---|---|---|
| Target | 1 GB boxes | machines with real resources |
| FDD hook and rules | no | yes |
| Hook dependencies | none (Node built-ins) | sql.js, PGlite |
| ECharts build | UMD, classic scripts | ES module |

Which hosts get which edition, in more detail: [Lite or full](operations/nf/lite-vs-full.html). The Caddy front door
redirects the bare URL to the Lite dashboard when `APP_ID=open-fdd-lite`.

To move a box off the old `bench-viz` app, follow the migration steps in the
[Lite README](https://github.com/bbartling/open-fdd/blob/master/lite/README.md).
