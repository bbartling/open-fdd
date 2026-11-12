# Open-FDD Lite

The small-box edition of Open-FDD for Normal Framework (NF). A tag-driven dashboard, charts,
a view of NF's BACnet server, RDF export and an Open-Meteo weather hook mirrored to NF's BACnet
server. **No FDD engine, no npm dependencies.** Built for 1 GB machines such as a Raspberry Pi 3.

NF app id `open-fdd-lite` (NF derives the id from the name "Open-FDD Lite": lower case,
non-alphanumerics become "-"). It was previously the "Bench Viz" bench app.

## What is in it

| Path | What |
|---|---|
| `app.json` | NF app manifest (application + files + hooks), same format as `nf-app/app.json`, used by `scripts/nf/hooks/nf_app_sync.py` |
| `static/index.html`, `app.js` | Tabbed dashboard: Overview, Charts, Points, BACnet Server, Model & RDF. The top bar has only the site picker; each tab that needs an equip has its own picker (plus a "Weather" entry). `app.js` just starts the shared shell |
| `static/app-core.js` | The dashboard shell (shared with Full, source `shared/static/`): top bar, equip pickers, tab router, the five tabs, live loop |
| `static/charts.js`, `chart.html`, `chart-page.js` | Chart catalog and range helpers (shared with Full; the default range is the last 7 days), NF-resampled history, one chart drawn at a time, and a one-chart-per-window page |
| `static/model.js` | Haystack model loader (sites, equips, devices, points by markers and refs) and RDF/Turtle export |
| `static/tree.html`, `tree.js`, `tree.css` | Read-only page: NF's BACnet server objects plus the Haystack device tree |
| `static/nf.js` | Shared NF access: console auth (LAN, or Clerk `ConsoleJWT` through Normal Online), `api`, `queryAll`, BACnet helpers |
| `static/base.css`, `style.css`, `theme-init.js`, `theme.js` | The shared CSS base (tokens, light "blueprint" / dark), Lite's own rules on top, and the shared theme layer (live light / dark switch, ECharts themes; same `openfdd-ui-theme` localStorage key) |
| `static/vendor/echarts.min.js` | ECharts 6.1.0 (UMD build, Apache-2.0), served by NF so the pages need no internet |
| `hooks/open_meteo_weather.js` | Weather hook: Open-Meteo to 3 hook variables and 3 BACnet analog values |
| `tests/lite.test.mjs` | `node --test lite/tests/lite.test.mjs` |

Everything is rendered from the Haystack model in NF. Nothing site-specific lives in the code:
to support a new site, tag its points in NF.

## Weather hook

Runs every 20 minutes (`MODE_SCHEDULED`).

- **Location** comes from NF: `GET /api/v1/sites?pageSize=500` (`latitude`, `longitude`, `name`).
  One site with coordinates is used automatically; with several, set the app option `site`
  (NF console, app settings; NF drops hook-level config) to the site id. Set the coordinates in NF (Sites), not in code.
- **Variables:** `oa_dry_bulb_web`, `oa_rh_web`, `oa_dewpoint_web` (NF points with history).
- **BACnet mirror:** analog values on NF's own BACnet server, named `WEB OA-T`, `WEB OA-H`,
  `WEB OA-DP`. NF drops hook-level config, so these are app options (set them in the NF console app settings):

  | key | default | meaning |
  |---|---|---|
  | `site` | `""` | NF site id, only needed when several sites have coordinates |
  | `weather` | on | `false` = off: no outbound request, the hook returns `{skipped: true, reason: "weather disabled"}` |
  | `exporters` | `bacnet-av` when NF's BACnet server is present | `none` = hook variables only; see [install reference](../docs/install.md) |
  | `bacnetMirror` | on (both editions; no setting needed) | `false` removes `bacnet-av` from the exporters (alias `bacnet_mirror`) |
  | `avInstances` | `[1, 2, 3]` | AV instance numbers for temp, RH, dewpoint (three distinct integers; an array or `"1,2,3"`) |

  The `bacnet_object` attrs on the global variables in `app.json` are informational labels. If you
  change `avInstances`, update them to match.
- NF creates the objects with its own uuids. Never pass an existing point uuid to
  `POST /api/v1/bacnet/local`: it overwrites that point.
- The weather points only show up on the dashboard when they are tagged in NF (`weather` marker and
  a `weatherStationRef`); the hook does not tag them.

## Deploy

```
python3 scripts/nf/hooks/nf_app_sync.py --env <console env> push lite/app.json
```

`--env` is the file with `CONSOLE_USERNAME`, `CONSOLE_PASSWORD` and `NF_CONSOLE_URL`. Other actions:
`status`, `run` (run the hook once now), `diff`, `pull`. The page is then at
`/api/v1/apps/static/open-fdd-lite/`. The sync script stamps each local script and stylesheet reference
in the HTML with a content hash, so browsers do not mix old and new files for NF's 5-minute cache.

The manifest asks for API key scopes `normalgw.hpl.v1/v2.readwrite` (variable history),
`normalgw.bacnet.v1/v2.readwrite` (the BACnet mirror) and `normalgw.ontology.v1.readonly`. They matter
once NF's own login is enabled: without scopes the hook's SDK calls get 401. On a box with auth bypass
they are harmless. The BACnet scope names are the ones from the NF scope list; check them on first deploy.

## Lite vs the full `nf-app/`

| | Open-FDD Lite (`lite/`) | Open-FDD (`nf-app/`) |
|---|---|---|
| App id | `open-fdd-lite` | `open-fdd` |
| Target | 1 GB boxes (Raspberry Pi 3) | machines with real resources |
| FDD hook and rule engines | no | yes (SQL engines, RCx library, rule packs) |
| Hook dependencies | none (Node built-ins) | sql.js, PGlite (`package.json`) |
| Pages | dashboard, charts, points, BACnet server, model + RDF, tree | the same, plus FDD, RCx, energy, fault plots |
| Weather hook | variables + BACnet mirror (av.N configurable) | the same (one shared hook) |
| ECharts | UMD build, classic scripts, 6.1.0 | ES module build |
| Theme | same light/dark tokens (reload on switch) | same tokens, live switch |
| Model/RDF export | the Bench Viz-era `model.js` | newer export |

Both can run on the same NF, but on a small box run only Lite.

## Migrating a box that runs `bench-viz`

Do this by hand; nothing here deploys anything.

1. Push `open-fdd-lite` next to the old app: `nf_app_sync.py ... push lite/app.json`. The old
   `bench-viz` app and its `open-meteo-weather` hook keep running.
2. Make sure the NF site has latitude/longitude (Sites). The old hook had Madison hard-coded; the new one
   reads NF. `nf_app_sync.py ... run lite/app.json` runs it once; check the run state and the log line.
3. The new hook has its own global variables (same labels, new point uuids). Tag them as the old ones were
   (`weather` marker, `weatherStationRef`, class/unit) so the dashboard and charts pick them up.
   Compare Lite's pages (`/api/v1/apps/static/open-fdd-lite/`) with Bench Viz's.
4. The BACnet AVs: both hooks would write av.1-3 (`avInstances` defaults to 1-3, the old objects are found
   and updated, not recreated). To avoid two writers, disable or stop the old hook before the new hook's first
   scheduled run, or set `avInstances` to other numbers for the overlap (then the old objects stay as they are
   until you delete them with `DELETE /api/v1/bacnet/local/OBJECT_ANALOG_VALUE/{n}`).
5. When satisfied, retire `bench-viz`: delete the old hook and then the old app (NF console or MCP
   `manage_app`). Old variable history stays with the old points; chart ranges on the new points start from the
   first Lite run.
6. Browser bookmarks and any `http://<box>/` redirect that pointed at `.../static/bench-viz/` need the new
   URL `.../static/open-fdd-lite/`.

## ECharts 6.1.0 notes

Vendored from `npm pack echarts@6.1.0` (`dist/echarts.min.js`, UMD, global `echarts`). Lite uses only
classic chart types (line, heatmap, scatter, bar, candlestick, tree) and none of the options that ECharts 6 removed or
changed incompatibly. ECharts 6 does change default styling (palette, axis and label defaults): Lite sets
palette, axis, tooltip and zoom colors explicitly from the registered ECharts themes in the shared `theme.js` (the same
ones the Full edition uses), so charts look the same in light and dark. The test suite renders each chart type with the vendored build.
