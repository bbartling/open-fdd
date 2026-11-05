# Open-FDD as a Normal Framework app (`nf-app/`)

Open-FDD packaged as **one Normal Framework (NF) application**, id `open-fdd`
([ADR-014](../docs/architecture/adr-014-open-fdd-as-nf-plugin.md),
[migration plan](../docs/migration/nf-plugin/PLAN.md)). NF does the field bus, the point model
(Haystack tags), the history, auth, remote access and backups; this app adds the Open-FDD UI and
hooks. **Status: slice 1** — UI + weather hook; the FDD rule runner arrives in slices 2–5.

| Path | What | Run by |
|---|---|---|
| `static/` | Open-FDD UI: Overview · Charts · Points · BACnet Server · Model & RDF, plus `chart.html` (one chart per window) and `tree.html` | NF serves it at `/api/v1/apps/static/open-fdd/` |
| `static/nf.js` | NF access: login (LAN or Normal Online/Clerk), `api()`, live push stream (`/api/v1/point/updates/data`) | browser |
| `static/model.js` | Haystack model loader (sites, equips, devices, tagged points) + RDF/Turtle export | browser |
| `static/charts.js` | Chart catalog; history resampled by NF (`/api/v1/point/data?window=…&method=…`) | browser |
| `static/theme*.js`, `style.css` | Light "blueprint" (default) and dark themes, `openfdd-ui-theme` in localStorage | browser |
| `static/vendor/echarts.esm.min.js` | ECharts 5.5.1 ES module (Apache-2.0, sha256 matches jsDelivr) | browser |
| `hooks/weather.js` | Open-Meteo outdoor air every 20 min → global variables; site coordinates from NF `/api/v1/sites` | NF Node runtime |
| `app.json` | Manifest: application, file map, hook definitions | `scripts/nf/hooks/nf_app_sync.py` |
| `tests/` | `node --test nf-app/tests/*.test.mjs` (model, RDF, chart selection, weather site) | CI |

## Deploy

```bash
# env file outside git: NF_CONSOLE_URL, CONSOLE_USERNAME, CONSOLE_PASSWORD
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_console.env push nf-app/app.json
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_console.env push nf-app/app.json --skip-hooks   # UI only
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_console.env diff nf-app/app.json
```

Or with the NF MCP connector: `manage_app write_file` per file and `deploy_hook` for hooks
(the 1 MB ECharts file is easier through `nf_app_sync.py`). NF derives an app's id from its
**name**, so `application.id` must equal the slug of `application.name` (CI checks it).

## Rules this app follows

- **Nothing site-specific in code:** sites, equips and points come from NF's Haystack model
  (markers + `siteRef` / `equipRef` / `deviceRef`); the weather hook reads coordinates from NF.
- **Strict CSP:** no inline scripts or styles, no CDN; `<meta http-equiv="Content-Security-Policy">`
  on every page.
- **Light on the box:** history is averaged by NF, one chart is drawn at a time, live values are
  pushed by NF instead of polled.
- **RDF:** the Model & RDF tab's Turtle is valid (Oxigraph + rdflib) with no dangling refs or orphans.

## Profiles

- **edge-lite** (small boxes, e.g. a Raspberry Pi): this app alone; NF's Redis history (7 days).
- **full** (≥ 4 GB RAM): the same app plus NF's TimescaleDB integration for long history and the
  SQL FDD pack (slice 5).

Front door (Caddy: dashboard open, console and writes behind a login, optional self-signed TLS)
arrives with slice 7.

Step-by-step install, MCP deploy recipe and troubleshooting: [docs/install/nf-plugin.md](../docs/install/nf-plugin.md).
