# OpenClaw bench E2E test modes

This folder defines the **bench-oriented test modes** for Open-FDD.

Use these modes when you want to validate a test-bench deployment without guessing which services should be running.

## Modes

- **full-stack** — DB + API + frontend + Caddy + BACnet server + BACnet scraper + weather + FDD loop
- **knowledge-graph-only** — DB + API + frontend + Caddy
- **data-ingestion-only** — DB + BACnet server + BACnet scraper
- **engine-only** — DB + FDD loop + weather scraper
- **bench-bacnet** — fake BACnet devices + collector path + graph sync checks

## Canonical commands

From repo root:

```bash
./scripts/bootstrap.sh                    # full-stack
./scripts/bootstrap.sh --mode model       # knowledge-graph-only
./scripts/bootstrap.sh --mode collector   # data-ingestion-only
./scripts/bootstrap.sh --mode engine      # engine-only
./scripts/bootstrap.sh --with-mcp-rag     # full-stack plus doc retrieval sidecar
./scripts/bootstrap.sh --test             # CI-style checks
```

## Auth preflight (do this first)

Most model / parity / hot-reload checks need authenticated backend access when Open-FDD auth is enabled.

Recommended order:
- load the active `stack/.env` into the shell, or set `OFDD_API_KEY`
- for split setups, point `OPENCLAW_STACK_ENV` at the active `.env`
- treat `401` / `403` during preflight as **auth/runtime-context drift**, not immediate product failure

The bench scripts now fail fast on missing/invalid auth instead of flooding the console with downstream 401 noise.

## What to test in each mode

- **full-stack**
  - service startup
  - API health
  - BACnet reachability
  - graph sync
  - frontend smoke checks
  - docs/context endpoint

- **knowledge-graph-only**
  - RDF config seed
  - `/mcp/manifest`
  - `/model-context/docs`
  - export/import endpoints
  - SPARQL queries

- **data-ingestion-only**
  - BACnet server startup
  - fake device discovery
  - point scrape ingestion
  - telemetry persistence

- **engine-only**
  - rule execution
  - weather feed
  - fault generation/observation
  - long-run stability

## Helper files

- `1_e2e_frontend_selenium.py` — UI smoke path
- `2_sparql_crud_and_frontend_test.py` — graph + CRUD + UI
- `3_long_term_bacnet_scrape_test.py` — persistence / soak test
- `4_hot_reload_test.py` — dev ergonomics regression
- `automated_suite.py` — orchestrator

## Contributing back upstream

Keep any new tools in this folder or under `bench/` so they can be reviewed, documented, and upstreamed cleanly into Open-FDD later.
