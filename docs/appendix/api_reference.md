---
title: API Reference
parent: Appendix
nav_order: 0
---

# API Reference

The Open-FDD platform exposes a **REST API** (port 8000) for CRUD, config, data model, bulk download, analytics, BACnet proxy, faults, and jobs. **Use the React frontend** (http://localhost:5173) for normal workflows—sites, points, config, faults, plots. Use the API when integrating scripts or cloud export.

**Interactive docs:** When the API is running, open **Swagger UI** at [http://localhost:8000/docs](http://localhost:8000/docs) or **ReDoc** at [http://localhost:8000/redoc](http://localhost:8000/redoc). Full **OpenAPI 3.1** spec: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json). When `OFDD_API_KEY` is set (e.g. in `stack/.env`), click **Authorize** in Swagger and paste the key so **Try it out** works.

---

## High-level overview

| Area | Purpose |
|------|---------|
| **CRUD** | **Sites** — list, create, get, update, delete (cascade to equipment, points, timeseries, fault results). **Equipment** — list, create, get, update, delete (cascade to points). **Points** — list, create, get, update, delete (cascade to timeseries). Points can include `bacnet_device_id` and `object_identifier` so the BACnet scraper polls them. |
| **Config** | **GET/PUT /config** — platform config (rule interval, BACnet scrape interval, Open-Meteo, etc.) stored in the RDF graph. The React Config page uses these. |
| **Data model** | **GET /data-model/export** — BACnet discovery + DB points (for LLM tagging). **PUT /data-model/import** — bulk create/update points and equipment. **GET /data-model/ttl** — Brick + BACnet TTL. **POST /data-model/sparql** — run SPARQL. **POST /data-model/reset** — reset graph to DB-only. |
| **Download** | **GET/POST /download/csv** — timeseries CSV (wide or long). **GET /download/faults** — fault results (CSV or JSON). Excel-friendly; timestamps in UTC (Z). |
| **Analytics** | **GET /analytics/fault-summary**, **GET /analytics/fault-timeseries** — fault counts and time-series for charts. **GET /analytics/motor-runtime** — fan/VFD runtime (data-model driven). **GET /analytics/system/*** — host/container/disk metrics. |
| **BACnet** | **GET /bacnet/gateways** — list gateways. **POST /bacnet/server_hello**, **POST /bacnet/whois_range**, **POST /bacnet/point_discovery**, **POST /bacnet/point_discovery_to_graph** — proxy to diy-bacnet-server; discovery-to-graph feeds the data model. **POST /bacnet/write_point** — write value (audited; third-party integrations use this for audited writes). |
| **Faults** | **GET /faults/active**, **GET /faults/state**, **GET /faults/definitions** — active state, full state, definitions. |
| **Jobs** | **POST /jobs/bacnet/discovery**, **POST /jobs/fdd/run** — async BACnet discovery and FDD run. **GET /jobs/{job_id}** — status. |
| **Run FDD** | **POST /run-fdd** — trigger FDD run now. **GET /run-fdd/status** — last run. |
| **AI** | **POST /ai/agent** — Overview chat (mode `overview_chat`). See [Overview AI context and behavior](#overview-ai-context-and-behavior) below. |

**Base URL:** `http://localhost:8000` (use your host or IP when remote). **Auth:** When `OFDD_API_KEY` is set, send `Authorization: Bearer <key>`; the React frontend does this when built with `VITE_OFDD_API_KEY`.

---

## Overview AI context and behavior

**POST /ai/agent** (mode `overview_chat`) powers the Overview AI assistant in the React UI. The backend calls OpenAI with the following context; the browser never talks to OpenAI directly.

### What the agent receives on each request

1. **Live context (JSON)** — Built from the database and graph on every request: data model summary (sites, equipment, points, rule definitions), active fault count, last FDD run status (and error message if the run failed), BACnet summary, graph serialization status.
2. **Platform documentation excerpt** — The first **~28,000 characters** of `pdf/open-fdd-docs.txt` (or the file at `OFDD_DOCS_PATH` if set). This gives the agent enough to explain what Open-FDD is, quick start, stack, and key concepts. The **full doc is not sent** (the file is ~213k characters / ~56k tokens); a fixed cap keeps token usage and cost reasonable. The excerpt is loaded once per request; there is no “fetch more doc as needed” (no RAG or chunk retrieval).
3. **Attached data** — The backend always attaches fault and sensor charts and tabular data for the last 24 hours; the model is told these are attached and should describe what they show.

### What the agent does *not* use

- **Conversation history** — Each request is **stateless**. The API does not send prior messages or replies to OpenAI. The UI may show a scroll of past Q&A, but the backend has no access to that; every call is a single user question and a single assistant reply. Multi-turn or “get more context as needed” in a thread is not implemented.

### Models and keys

- **Models** — The API accepts any `model` string; the frontend offers **GPT-5 mini** (default, cost-efficient) and **GPT-5.4 pro** (for more complex tasks). No 4o or other model names are assumed in the docs.
- **OpenAI API key** — Sent in the request body; used by the backend for that request only and never stored.
