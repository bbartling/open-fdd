# Fork customization map — ~70% built, vibe the rest

Open FDD Vibe Coder is a **template**: data loading, FDD rules, charts, tune API, and deploy packaging are done. Forks change branding, pages, rules, and UI chrome — not the pandas engine from scratch.

## Modes

| `DASHBOARD_MODE` | Use when |
| --- | --- |
| `full` (default) | Local analyst — HTML shells + tune sliders + export |
| `api` | Custom front end — **same JSON API**, no `*.html` shells; charts still arrive as HTML in `POST /api/refresh/{page_id}` → `content` (Flavor A) |
| `deploy` | Client delivery — pre-baked `site/` + optional live notes |

Start with `full`. Switch to `api` when you want your own nav/layout but keep server-rendered Plotly fragments.

## Stable API contract (Flavor A)

| Endpoint | Returns |
| --- | --- |
| `GET /api/pages` | Nav tree (SPARQL-driven) |
| `GET /api/session` | Auth flags + `site_settings` |
| `GET /api/config?page=…` | Params, sliders metadata, notes |
| `POST /api/config` | Merge session (engineer edit) |
| `POST /api/refresh/{page_id}` | `{ content: "<html>…", analytics, params }` |
| `GET /api/rules` | Custom plugin catalog |
| `POST /api/rules/run` | Run a plugin; `{ chart, summary }` |
| `GET /api/rdf/*` | Haystack model + SPARQL |
| `GET /docs` | OpenAPI explorer |

**Phase 2 (Flavor B):** optional `figures[]` JSON instead of HTML — not required to fork.

## Morph points (edit these)

| Goal | Where |
| --- | --- |
| Custom fault / ML rule | `fdd_app/backend/rules/plugins/*.py` |
| New dashboard page | `page_registry.py` + `body_*` in `generate_dashboard.py` |
| Tune thresholds | `dashboard_params.py` (`PARAM_DEFS`) |
| Reskin UI | `static/dashboard.css`, `static/dashboard_theme.js` |
| Analyst behavior | `static/dashboard_tune.js`, `dashboard_auth.js`, `dashboard_settings.js` |
| Data root / building | `shared/data_config.py`, `.env`, `data_paths.local.yaml` |
| Occupancy / comfort | `shared/occupancy.py` + session `site_settings` |

## Do not (agents)

- SPARQL on every chart refresh for path discovery
- `exec()` / upload arbitrary Python via API
- Rewrite all rules in Arrow without parity tests
- Block HTTP on full pandas recompute when cache can serve warm results

## Cookbook rules inventory (still in repo)

All Open-FDD-style rules from pre–mega-reorg are in `generate_dashboard.py` + `dashboard_params.py`:

- **AHU FC:** FC1, FC2/FC3, FC4 (hunting), FC8–FC13, free-cool opp, ECON-2/3 (Open-Meteo)
- **Sensors:** SV-1/2/4/6/7, WS-OAT, DATA-QA
- **Comfort / zones:** COMFORT, unoccupied fan
- **Plant:** CHILLER-DT/EN, BOILER-WARM/DT, EXCESS-FAN
- **Economizer diagnostics page:** `economizer_fdd_engine.py` (ECON_NOT_ECONOMIZING, MECH_COOLING, damper stuck, MAT plausibility, …)
- **Custom plugins:** `rules/plugins/` (pandas + sklearn examples)

45 tunable params · 25 rule groups in `PARAM_DEFS`. Mega-reorg **reorganized UI** (ECM cards, plant split, rules lab); it did **not** remove cookbook logic.

## Three fork recipes

### 1. Add a custom fault

1. Copy `rules/plugins/custom_sat_hunting.py` → `my_rule.py`
2. Define `RULE` manifest + `compute(ctx) -> RuleResult`
3. Restart server; open **Custom Rules** page or `POST /api/rules/run`

### 2. Reskin (keep charts)

1. Edit `static/dashboard.css` (CSS variables, ECM cards)
2. Optionally replace header/nav in `generate_dashboard.py` `page_html()` shell
3. Stay on `full` or use `api` + your own shell calling `/api/refresh`

### 3. Point at your CSV tree

1. Copy `data_paths.example.yaml` → `data_paths.local.yaml`
2. `python validate_data.py`
3. `python app.py`
