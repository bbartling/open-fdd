---
title: API Reference
parent: Appendix
nav_order: 0
---

# API Reference

The Open-FDD platform exposes a **REST API** (port 8000) for CRUD, config, data model, bulk download, analytics, BACnet proxy, faults, and jobs. **Use the React frontend** (http://localhost:5173) for normal workflows—sites, points, config, faults, plots. Use the API when integrating scripts, cloud export, or Home Assistant.

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
| **BACnet** | **GET /bacnet/gateways** — list gateways. **POST /bacnet/server_hello**, **POST /bacnet/whois_range**, **POST /bacnet/point_discovery**, **POST /bacnet/point_discovery_to_graph** — proxy to diy-bacnet-server; discovery-to-graph feeds the data model. **POST /bacnet/write_point** — write value (audited; HA/Node-RED use this only). |
| **Faults** | **GET /faults/active**, **GET /faults/state**, **GET /faults/definitions** — active state, full state, definitions. |
| **Jobs** | **POST /jobs/bacnet/discovery**, **POST /jobs/fdd/run** — async BACnet discovery and FDD run. **GET /jobs/{job_id}** — status. |
| **Run FDD** | **POST /run-fdd** — trigger FDD run now. **GET /run-fdd/status** — last run. |

**Base URL:** `http://localhost:8000` (use your host or IP when remote). **Auth:** When `OFDD_API_KEY` is set, send `Authorization: Bearer <key>`; the React frontend does this when built with `VITE_OFDD_API_KEY`.
