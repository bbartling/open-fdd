---
title: API Reference
parent: Appendix
nav_order: 0
---

# API Reference

The Open-FDD **FastAPI** app exposes a **REST API** (default port **8000**) for CRUD, config, data model, bulk download, analytics, **legacy** BACnet proxy routes (if you enable a lab gateway), faults, and jobs. It is **not** started by the default **`bootstrap.sh`** or slim **Compose** — run it with **`uvicorn`** from a dev install when you need REST/SPARQL/modeling. **Use the React frontend** (e.g. http://localhost:5173 with `npm run dev` under `afdd_stack/frontend/`) for workflows such as sites, points, config, faults, and plots. Use the API for scripts, Open‑Claw, and cloud export.

**Interactive docs:** When the API is running, open **Swagger UI** at [http://localhost:8000/docs](http://localhost:8000/docs) or **ReDoc** at [http://localhost:8000/redoc](http://localhost:8000/redoc). Full **OpenAPI 3.1** spec: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json). When `OFDD_API_KEY` is set (e.g. in `afdd_stack/stack/.env`), click **Authorize** in Swagger and paste the key so **Try it out** works.

---

## High-level overview

| Area | Purpose |
|------|---------|
| **CRUD** | **Sites** — list, create, get, update, delete (cascade to equipment, points, timeseries, fault results). **Equipment** — list, create, get, update, delete (cascade to points). **Points** — list, create, get, update, delete (cascade to timeseries). **`external_id`** aligns with **VOLTTRON** historian / topic naming; optional `bacnet_*` columns are **metadata**, not live wire ingest. |
| **Config** | **GET/PUT /config** — platform config (rule interval, **legacy** BACnet keys, Open-Meteo, etc.) stored in the RDF graph. The React Config page uses these. |
| **Data model** | **GET /data-model/export** — DB points + graph snapshot (for LLM tagging). **PUT /data-model/import** — bulk create/update points and equipment. **GET /data-model/ttl** — Brick TTL. **POST /data-model/sparql** — run SPARQL. **POST /data-model/reset** — reset graph to DB-only. |
| **Energy calculations** | **GET /energy-calculations/export?site_id=** — LLM bundle: `calc_types`, **`penalty_catalog`** (18 defaults), `energy_calculations`. **GET /energy-calculations/penalty-catalog** — narratives only. **POST /energy-calculations/seed-default-penalty-catalog?site_id=** (`replace=true` optional) — insert disabled `penalty_default_*` rows. **PUT /energy-calculations/import** — upsert by `(site_id, external_id)`. CRUD: **GET/POST/PATCH/DELETE /energy-calculations**, **POST /energy-calculations/preview**. See [AI-assisted energy calculations](../modeling/ai_assisted_energy_calculations) and [energy penalty catalog](../modeling/energy_penalty_equations). |
| **Download** | **GET/POST /download/csv** — timeseries CSV (wide or long). **GET /download/faults** — fault results (CSV or JSON). Excel-friendly; timestamps in UTC (Z). |
| **Analytics** | **GET /analytics/fault-summary**, **GET /analytics/fault-timeseries** — fault counts and time-series for charts. **GET /analytics/motor-runtime** — fan/VFD runtime (data-model driven). **GET /analytics/system/*** — host/container/disk metrics. |
| **BACnet (legacy lab proxy)** | **GET /bacnet/gateways**, **POST /bacnet/*** — only when **you** run a separate JSON-RPC gateway; **not** default ingest. Prefer **VOLTTRON** on site. |
| **Faults** | **GET /faults/active**, **GET /faults/state**, **GET /faults/definitions** — active state, full state, definitions. |
| **Jobs** | **POST /jobs/bacnet/discovery** (legacy), **POST /jobs/fdd/run** — async discovery (if enabled) and FDD run. **GET /jobs/{job_id}** — status. |
| **Run FDD** | **POST /run-fdd** — trigger FDD run now. **GET /run-fdd/status** — last run. |
| **Model context** | **GET /model-context/docs** — serve Open-FDD documentation as plain-text model context for external agents (supports excerpt/full/slice and keyword retrieval via `query`). |

**Base URL:** `http://localhost:8000` (use your host or IP when remote). **Auth:** When `OFDD_API_KEY` is set, send `Authorization: Bearer <key>`; the React frontend does this when built with `VITE_OFDD_API_KEY`.

---

## Model context docs endpoint

Open-FDD can serve its documentation as plain text model context via:

- `GET /model-context/docs`

This endpoint is designed for external LLM agents (OpenAI-compatible providers like Open‑Claw). Open-FDD does not embed or run an LLM; it only provides documentation context.

By default, `mode=excerpt` returns a truncated excerpt of `pdf/open-fdd-docs.txt` (or `OFDD_DOCS_PATH` if set). For more control:

- `mode=full` returns the entire file.
- `mode=slice&offset=...` returns a substring.
- `query=...` returns keyword-retrieved relevant doc sections (simple lexical matching) to help keep prompts smaller.

When `OFDD_API_KEY` auth is enabled, this endpoint requires Bearer auth like other API routes.
