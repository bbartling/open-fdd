---
title: Getting Started
nav_order: 3
---

# Getting Started

This page covers **prerequisites** and the **bootstrap script**: how to get the Open-FDD platform running. For deeper directions on verification, operations, data modeling, and rules, see the [How-to Guides](howto/verification).

---

## Prerequisites

- **OS:** Linux (Ubuntu Server latest, or Linux Mint), x86. Keep the system updated:
  ```bash
  sudo apt update && sudo apt upgrade -y
  ```
- **Docker and Docker Compose:** Required. Install Docker Engine and Docker Compose (or `docker-compose`). See [Docker install](https://docs.docker.com/engine/install/) for your distro.
- **Git:** To clone the project:
  ```bash
  git clone https://github.com/bbartling/open-fdd.git
  cd open-fdd
  ```
- **BACnet (default data driver):** The default data driver is BACnet. Bootstrap **automatically** builds and starts [diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server) as its own Docker container (plus the BACnet scraper). You must run **BACnet discovery first** and curate the resulting CSV before the platform can scrape data—the scraper uses that CSV as its config. See [BACnet → Setup](bacnet/index#setup) and [BACnet overview](bacnet/overview). To run without BACnet (e.g. central-only with remote gateways), start only the services you need (e.g. `docker compose up -d db grafana api fdd-loop weather-scraper` from `platform/`).

---

## What the bootstrap script does

`scripts/bootstrap.sh` builds and starts the platform, waits for Postgres to be ready (~15s), applies database migrations (idempotent), and prints service URLs. It does **not** purge or wipe the database; only `--reset-grafana` touches a volume (Grafana only). See [Danger zone](howto/danger_zone) for when data is purged.

**Full stack (default):** TimescaleDB, Grafana, API, **diy-bacnet-server** (BACnet/IP bridge), **BACnet scraper**, weather scraper, FDD loop. Bootstrap builds and starts the BACnet stack automatically; ensure you have run [BACnet discovery](bacnet/overview#discovery-first-then-curate-the-csv) and curated the CSV **before** relying on the scraper. Optional services (Caddy, host-stats) are in docker-compose; start them with `docker compose up -d` from `platform/` if needed.

**Bootstrap options:**

| Option | Effect |
|--------|--------|
| *(none)* | Build and start full stack. |
| `--verify` | List containers and test DB reachability; exit. Does not start or stop anything. |
| `--minimal` | Raw BACnet only: DB + Grafana + BACnet server + scraper. No FDD, weather, or API. See [Overview — Ways to deploy](overview#ways-to-deploy). |
| `--reset-grafana` | Wipe Grafana volume and re-apply provisioning. **Database and all other data are retained.** Use when dashboards or datasource are wrong. |
| `--retention-days N` | TimescaleDB retention: drop chunks older than N days (default 365). Written to `platform/.env` as `OFDD_RETENTION_DAYS`. |
| `--log-max-size SIZE` | Docker log max size per file (e.g. `100m`, `50m`). Default `100m`. Env: `OFDD_LOG_MAX_SIZE`. |
| `--log-max-files N` | Docker log max number of files per container (default 3). Env: `OFDD_LOG_MAX_FILES`. |

---

## Clone and run bootstrap

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/bootstrap.sh
# Optional: set edge limits at first run (saved to platform/.env)
# ./scripts/bootstrap.sh --retention-days 180 --log-max-size 50m --log-max-files 2
```

After a successful run you get DB (localhost:5432/openfdd), Grafana (http://localhost:3000, admin/admin), API (http://localhost:8000/docs), and BACnet Swagger (http://localhost:8080/docs). To update an existing clone and restart:

```bash
cd open-fdd
git pull
./scripts/bootstrap.sh
```

(Or `docker compose -f platform/docker-compose.yml up -d --build` from repo root if you only need to rebuild and restart.)

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

For **BACnet driver setup** (discovery → curate CSV → scrape): [BACnet](bacnet/index) and [BACnet overview](bacnet/overview). For data modeling and fault rules: [Data modeling](modeling/overview), [Fault rules for HVAC](rules/overview).
