# Dashboard UI spec (App 19)

Analyst-facing **static-first** RCx dashboard branded **Open FDD Vibe Coder**. Same look across buildings; only data, equipment pages, and copy change per fork.

**Template note:** page ids like `ahu_1` / `ahu_2` are the current reference layout — forks should rename/add pages to match discovered `AHU_*` folders. See [`../TEMPLATE.md`](../TEMPLATE.md).

---

## Visual system

Shared stylesheet: `static/dashboard.css` (Inter font, CSS variables). Theme toggle via `static/dashboard_theme.js` (`data-theme` light/dark, persisted in `localStorage`).

| Token | Dark | Use |
| --- | --- | --- |
| Background | `#0f1419` | Page bg |
| Card | `#1a2332` | Sections, ECM cards |
| Text | `#e8edf4` | Body |
| Muted | `#8b9cb3` | Labels, captions |
| Accent | `#3b82f6` | Links, primary buttons |
| Good / warn / bad | `#22c55e` / `#f59e0b` / `#ef4444` | Fault severity |

Chart palette: blue, green, amber, red, purple, cyan (see `COLORS` in `economizer_diagnostics_page.py`).

---

## Page structure

```html
<!-- render_page_html() wrapper -->
<nav> … hub links … </nav>
<header> building + date range + meta </header>
<main> … Plotly figures + tables … </main>
<footer> generated timestamp, poll interval note </footer>
```

### Standard pages (SPARQL-driven via `page_registry.py`)

| page_id | Purpose |
| --- | --- |
| `index` | Executive summary, ECM KPI cards, nav hub |
| `zones` | Comfort / zones by floor/season |
| `weather` | BAS vs reference weather, fault deltas |
| `ahu_{slug}` | Per-AHU trends (dynamic from model; legacy `ahu_1`/`ahu_2`) |
| `economizer` | Free cooling + merged economizer diagnostics |
| `chiller_plant` | Chillers + CHW metrics |
| `boiler_plant` | Boilers + HWS metrics |
| `motor_runtime` | All modeled fans/pumps/motors |
| `central_plant`, `excess_runtime` | Legacy aliases (still routable) |
| `data_model.html` | Haystack RDF / SPARQL explorer |

Unavailable equipment → placeholder card: “Not present in data model” (nav link grayed but reachable).

Nav: top bar + **Air-side Systems** dropdown from `GET /api/pages`.

---

## Plotly

- Self-contained: vendor `plotly.min.js` copied next to HTML
- Responsive width 100%; height per chart ~350–450px
- Hover unified where comparing AHU signals
- Downsample >10k points for file size

---

## ECM card layout

Each ECM block uses `ecm_card()` in `generate_dashboard.py`:

```html
<section class="ecm-card" data-ecm="ECM-1" data-rule="COMFORT">
  <header class="ecm-head">…</header>
  <div class="ecm-analytics" data-analytics-for="COMFORT">…</div>
  <div class="rule-tune-mount" data-rule="COMFORT"></div>
  <div class="ecm-chart">Plotly div</div>
  <footer class="ecm-equation">…</footer>
</section>
```

**No right rail** — sliders mount only inside ECM cards / matching `.rule-tune-mount` elements.

Analytics table filled from `/api/refresh` response `analytics.ecms` (fault hours, %). Export: `GET /api/analytics/export?format=csv|json`.

---

## Analyst panel (local full mode)

Injected by the FastAPI shell / `dashboard_tune.js` + `dashboard_auth.js` + `dashboard_settings.js`:

- **Rule-grouped tune boxes** — sliders grouped by Open-FDD rule id (GLOBAL, SV-*, FC*, ECON-*, …)
- **Inline ECM mounts only** — no sticky sidebar; synced slider duplicates removed
- **Site settings** — occupancy schedule, comfort setpoint/band, timezone (`analyst_session.json` → `site_settings`)
- **Engineer PIN** — `POST /api/login` / `logout`; `GET /api/session` → `{ engineer, locked, can_edit }`
- **Package lock** — export sets `package_locked`; read-only banner + disabled sliders until engineer login
- **Debounced live refresh** (~900 ms) on slider change (when `can_edit`)
- **Refresh** → `POST /api/refresh/<page_id>` → recompute **that page only** (cached by param hash)
- **Export session** → JSON + client zip via `package_dashboard.py`

Env: `ENGINEER_PIN`, `FLASK_SECRET_KEY` (see `.env.example`).

CSS: `.analyst-panel`, `.ecm-card`, `.rule-tune-box` — stack on `<900px`.

### Shell-first UX (full mode)

1. `GET /<page>.html` returns instant shell with “Loading charts…” placeholder (~0.05 s)
2. `dashboard_tune.js` loads `/api/config` then `POST /api/refresh/<page_id>`
3. Chart HTML replaces placeholder when compute completes

Do **not** block first paint on full pandas pipeline.

### Performance (full mode)

| Layer | Module | Behavior |
| --- | --- | --- |
| CSV load | `feather_cache.read_history_csv` + `dashboard_cache.get_raw_data()` | Feather sidecar; once per process; mtime invalidation |
| Path discovery | `raw_data_source_paths()` | Filesystem scan only — **no SPARQL per request** |
| Context compute | `compute_context(raw, page_id=…)` | Lazy per page; param-keyed cache |
| HTML body | `dashboard_cache.get_body()` | Cached Plotly HTML per page + params |
| Prewarm | `app.py` background thread | Warms index, ahu_1, ahu_2, economizer on startup |
| Econ diagnostics HTML | `should_rebuild_economizer_diagnostics()` | Skip rebuild when params unchanged |

Typical warm refresh: **&lt; 0.5 s** per page. First cold load: ~2 s CSV + ~10 s index compute (one-time).

See [`PERFORMANCE_AND_LOADING.md`](PERFORMANCE_AND_LOADING.md).

---

## Deploy mode (client)

- Pre-baked `site/*.html` only
- Served via Docker + Gunicorn (`Dockerfile.deploy`) or static zip
- Optional notes panel (`dashboard_notes.js`) when `ANALYST_ENABLED=1`
- Banner: *Read-only charts · rebuild site/ locally to update charts*

---

## Navigation

Index lists all pages with one-line description + fault hour badges where available.

File names: `{page_id}.html` lowercase, underscores.

---

## Copy / metadata

Each page meta block should include:

- Building id (from config, not hardcoded "Building 100" in new sites)
- Data range (min/max timestamp from loaded frames)
- Effective grid label (`effective_poll_seconds` or manifest `grid_minutes`)
- Rule version or git hash optional in footer

---

## Accessibility

- Sufficient contrast on dark theme
- Table summaries for fault rollups (not Plotly-only critical numbers)
- No CDN-only assets required for offline zip
