---
title: Getting Started
nav_order: 3
---

> **TODO:** This document previously referenced Home Assistant (HA) setup. HA integration has been removed from the project; any remaining HA mentions are for reference only and may be outdated.

# Getting Started

This page covers **prerequisites** and the **bootstrap script**: how to get the Open-FDD platform running. For deeper directions on verification, operations, data modeling, and rules, see the [How-to Guides](howto/verification).

---

## Do this to bootstrap

1. **Prerequisites:** Docker, Docker Compose, and Git installed (see below).
2. **Clone and run bootstrap** (from any directory):

   ```bash
   git clone https://github.com/bbartling/open-fdd.git
   cd open-fdd
   ./scripts/bootstrap.sh
   ```

   That’s it. The script builds and starts the full stack (DB, API, frontend, Caddy, diy-bacnet-server, BACnet scraper, weather scraper, FDD loop), waits for Postgres, runs migrations, and **seeds platform config** via the API (PUT /config) so runtime settings are in the knowledge graph. When it finishes you get:

   - **API:** http://localhost:8000/docs  
   - **Frontend:** http://localhost:5173 (or via Caddy http://localhost:80)  
   - **BACnet Swagger:** http://localhost:8080/docs  
   - **DB:** localhost:5432/openfdd (postgres/postgres)  
   - **Grafana:** not started by default; use `./scripts/bootstrap.sh --with-grafana` then http://localhost:3000 (admin/admin)

3. **Optional:** Set `OFDD_*` in `stack/.env` before the first run to customize the seeded config (e.g. `OFDD_BACNET_SERVER_URL`, `OFDD_RULE_INTERVAL_HOURS`). See [Configuration](configuration).

---

## Prerequisites

- **OS:** Linux only (Ubuntu Server latest, or Linux Mint). **Tested on x86;** should work on ARM but is untested. The bootstrap script and Docker stack are not supported on Windows. Keep the system updated:
  ```bash
  sudo apt update && sudo apt upgrade -y
  ```
- **Docker and Docker Compose:** Required. Install Docker Engine and Docker Compose (or `docker-compose`). See [Docker install](https://docs.docker.com/engine/install/) for your distro.
- **Git:** To clone the project:
  ```bash
  git clone https://github.com/bbartling/open-fdd.git
  cd open-fdd
  ```
- **BACnet (default data driver):** The default data driver is BACnet. Bootstrap **automatically** builds and starts [diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server) as its own Docker container (plus the BACnet scraper). You must run **BACnet discovery first** and curate the resulting CSV before the platform can scrape data—the scraper uses that CSV as its config. See [BACnet → Setup](bacnet/index#setup) and [BACnet overview](bacnet/overview). To run without BACnet (e.g. central-only with remote gateways), start only the services you need (e.g. `docker compose up -d db grafana api fdd-loop weather-scraper` from `stack/`).

---

## What the bootstrap script does

`scripts/bootstrap.sh` (run from the **repo root**):

1. Ensures **diy-bacnet-server** exists as a sibling repo (clones it if missing).
2. Runs **docker compose up -d --build** from `stack/` (builds all images, starts all services).
3. Waits for **Postgres** to be ready (~15s).
4. Applies **database migrations** (idempotent; safe on existing DBs).
5. **Seeds platform config** via PUT /config (waits for API, then sends default or `stack/.env` values into the RDF graph).
6. Optionally runs **--reset-data** if you passed that flag (deletes all sites + data-model reset; for testing).

It does **not** purge or wipe the database on a normal run; only `--reset-grafana` wipes the Grafana volume. See [Danger zone](howto/danger_zone) for when data is purged.

**Full stack (default):** TimescaleDB, Grafana, API, **diy-bacnet-server** (BACnet/IP bridge), **BACnet scraper**, weather scraper, FDD loop. For BACnet data you can use the **data model** (discover via API → import points) or a CSV; see [BACnet overview](bacnet/overview). Optional services (Caddy, host-stats) are in docker-compose; start them with `docker compose up -d` from `stack/` if needed.

**Bootstrap options:** Run `./scripts/bootstrap.sh --help` for the full list. Summary:

| Option | Effect |
|--------|--------|
| *(none)* | Build and start full stack (DB, API, frontend, Caddy, BACnet server, scrapers, FDD loop). Prints API key if generated. Grafana **not** started by default. |
| `--with-grafana` | Include Grafana; then accessible at http://localhost:3000 or via Caddy at `/grafana` if using a full Caddyfile. |
| `--minimal` | DB + BACnet server + bacnet-scraper only. No FDD, weather, or API. Add `--with-grafana` for Grafana. |
| `--verify` | Health checks only: list containers, test DB; exit. Does not start or stop. |
| `--test`, `--verify-code` | Run tests (frontend lint + typecheck, backend pytest, Caddy validate); then exit. |
| `--build SERVICE ...` | Rebuild and restart only listed services, then exit. Services: `api`, `bacnet-server`, `bacnet-scraper`, `caddy`, `db`, `fdd-loop`, `frontend`, `grafana`, `host-stats`, `weather-scraper`. |
| `--build-all` | Rebuild and restart all services; then exit. |
| `--frontend` | Before start: stop frontend container and remove `frontend_node_modules` volume so the next `up` runs a fresh `npm install`. Use after changing `frontend/package.json`. |
| `--update` | Git pull open-fdd and diy-bacnet-server (sibling), then rebuild and restart (keeps DB). |
| `--maintenance` | Safe Docker prune only (no volume prune). |
| `--reset-grafana` | Wipe Grafana volume and re-apply provisioning. DB and other data retained. |
| `--reset-data` | Delete all sites via API and POST /data-model/reset (testing). |
| `--retention-days N` | TimescaleDB retention in days (default 365). Env: `OFDD_RETENTION_DAYS`. |
| `--log-max-size SIZE` | Docker log max size per file (default `100m`). Env: `OFDD_LOG_MAX_SIZE`. |
| `--log-max-files N` | Docker log max files per container (default 3). Env: `OFDD_LOG_MAX_FILES`. |
| `--install-docker` | Attempt Docker install (Linux) then continue. |
| `--no-auth` | Do not generate or set `OFDD_API_KEY`; API will not require Bearer auth. |

To **update** an existing clone: `git pull` then `./scripts/bootstrap.sh`, or `./scripts/bootstrap.sh --update`. Rebuild single services: `./scripts/bootstrap.sh --build api`.

---

## After bootstrap

- **Grafana:** Open http://localhost:3000. TimescaleDB datasource and Open-FDD dashboards are provisioned from config. If dashboards or datasource are wrong, run `./scripts/bootstrap.sh --reset-grafana` (keeps DB data).
- **Minimal mode:** If you used `--minimal`, only DB, Grafana, BACnet server, and scraper run. No API; use Grafana and scraper logs to confirm data flow. To add the full stack later, run `./scripts/bootstrap.sh` without `--minimal`.

---

## Deeper directions: How-to Guides

For step-by-step procedures and reference, use the howto guides:

- **[Quick reference](howto/quick_reference)** — One-page cheat sheet (endpoints, docker commands, data flow checks, logs).
- **[Verification](howto/verification)** — Health checks, data flow (curl and DB), logs, weather scraper, FDD loop, Grafana provisioning.
- **[Operations](howto/operations)** — Start/stop/restart, when to rebuild, run FDD now, migrations, resource check, database, unit tests.
- **[Danger zone](howto/danger_zone)** — When data is purged, CRUD cascade, how to wipe and start over.
- **[Security & Caddy](security)** — Basic auth, throttling, TLS.

For **BACnet driver setup** (discovery → curate CSV → scrape): [BACnet](bacnet/index) and [BACnet overview](bacnet/overview). For data modeling and fault rules: [Data modeling](modeling/overview), [Fault rules for HVAC](rules/overview). To run a simple BACnet + CRUD smoke test with your instance range: `python tools/bacnet_crud_smoke_test.py --start-instance 1 --end-instance 3456999`. For the full CRUD + SPARQL e2e test: `python tools/graph_and_crud_test.py` (see [SPARQL cookbook](modeling/sparql_cookbook)).
