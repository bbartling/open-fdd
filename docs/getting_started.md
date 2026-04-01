---
title: Getting Started
nav_order: 3
---

# Getting Started

This page covers **prerequisites** and the **bootstrap script**: how to get the Open-FDD platform running. For configuration, data modeling, and rules, see the [Documentation](index#documentation) index.

---

## Do this to bootstrap

1. **Prerequisites:** Docker, Docker Compose, and Git installed (see below).
2. **Clone and run bootstrap** (from any directory):

   ```bash
   git clone https://github.com/bbartling/open-fdd.git
   cd open-fdd
   ./scripts/bootstrap.sh
   ```

   Partial module modes are also supported:

   ```bash
   ./scripts/bootstrap.sh --mode collector
   ./scripts/bootstrap.sh --mode model
   ./scripts/bootstrap.sh --mode engine
   ```

   **Optional one-liner (HTTPS + login):** Piping your password on stdin lets bootstrap create a Phase 1 dashboard user, generate a self-signed certificate for Caddy (then use `https://localhost/`; the browser will warn until you trust the cert), set `stack/.env` for TLS-aware cookies on the API, and start the same full stack as a plain `./scripts/bootstrap.sh`.

   ```bash
   printf '%s' 'YOUR_PASSWORD' | ./scripts/bootstrap.sh --user YOURNAME --password-stdin --caddy-self-signed
   ```

   That’s it. The script builds and starts the full stack (DB, API, frontend, Caddy, diy-bacnet-server, BACnet scraper, weather scraper, FDD loop), waits for Postgres, runs migrations, and **seeds platform config** via the API (PUT /config) so runtime settings are in the knowledge graph. When it finishes you get:

   - **API:** http://localhost:8000/docs  
   - **Frontend:** http://localhost:5173 (or via Caddy http://localhost:80). See [Using the React dashboard](frontend) for what each page does.  
   - **BACnet Swagger:** http://localhost:8080/docs  
   - **DB:** `127.0.0.1:5432`/openfdd (postgres/postgres) — bound to loopback only; not exposed on the LAN.  

---

## External Agentic AI (OpenAI-compatible)

Open‑FDD does not embed an LLM. Instead, external AI agents (for example an OpenAI-compatible tool like Open‑Claw) can take advantage of Open‑FDD by calling its APIs:

1. Export the current data model JSON: `GET /data-model/export`
2. Fetch documentation as model context: `GET /model-context/docs` (optionally with `query=...` / keyword retrieval)
3. Import tagged JSON back into the platform: `PUT /data-model/import`

Manual Data Model export/import (JSON) always works without any AI.

See [Open‑Claw integration](openclaw_integration) and [API Reference](appendix/api_reference) for endpoint details.

Optional MCP RAG profile:

```bash
./scripts/bootstrap.sh --with-mcp-rag
```

This starts an MCP-style retrieval sidecar at `http://localhost:8090` using derived index artifacts from canonical docs.

---

## Prerequisites

- **OS:** Linux only (Ubuntu Server latest, or Linux Mint). Maintainers primarily test **x86_64**; and the project has been tested successful on ARM with a **ARM64** (e.g. Raspberry Pi 4/5) has been reported working with Docker—expect to validate image availability and sizing (RAM/CPU) yourself. The bootstrap script and Docker stack are not supported on Windows. Keep the system updated:
  ```bash
  sudo apt update && sudo apt upgrade -y
  ```
- **Docker and Docker Compose:** Required. Install Docker Engine and Docker Compose (or `docker-compose`). See [Docker install](https://docs.docker.com/engine/install/) for your distro.
- **Git:** To clone the project:
  ```bash
  git clone https://github.com/bbartling/open-fdd.git
  cd open-fdd
  ```
- **BACnet (default data driver):** The default data driver is BACnet. Bootstrap **automatically** builds and starts [diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server) as its own Docker container (plus the BACnet scraper). Run **BACnet discovery** from the UI or API, then add points to the **data model** (with `bacnet_device_id` / `object_identifier`)—the scraper reads **only the database + graph**, not a CSV file. See [BACnet → Setup](bacnet/index#setup) and [BACnet overview](bacnet/overview). To run without BACnet (e.g. central-only with remote gateways), start only the services you need (e.g. `docker compose --profile grafana up -d db api fdd-loop weather-scraper grafana` from `stack/` if you want optional Grafana).

---

## What the bootstrap script does

`scripts/bootstrap.sh` (run from the **repo root**):

1. Ensures **diy-bacnet-server** exists as a sibling repo (clones it if missing).
2. Runs **docker compose up -d --build** from `stack/` (builds all images, starts all services).
3. Waits for **Postgres** to be ready (~15s).
4. Applies **database migrations** (idempotent; safe on existing DBs).
5. **Seeds platform config** via PUT /config (waits for API, then sends default or `stack/.env` values into the RDF graph).
6. Optionally runs **--reset-data** if you passed that flag (deletes all sites + data-model reset; for testing).


**Full stack (default):** 
* TimescaleDB, API, **diy-bacnet-server** (BACnet/IP bridge), **BACnet scraper**, weather scraper, FDD loop,  **CADDY** reverse proxy with self signed certs on TLS run:
```bash
printf '%s' 'YOUR_PASSWORD' | ./scripts/bootstrap.sh --user YOURNAME --password-stdin --caddy-self-signed
```


**Bootstrap options:** Run `./scripts/bootstrap.sh --help` for the full list. Summary:

| Option | Effect |
|--------|--------|
| *(none)* | Build and start full stack (DB, API, frontend, Caddy, BACnet server, scrapers, FDD loop). Prints API key if generated. Grafana and MQTT broker **not** started by default. |
| `--with-grafana` | **Optional:** include Grafana at http://localhost:3000 (admin/admin). Add a `/grafana` route in Caddy when you extend the Caddyfile (see [Security](security)). |
| `--with-mqtt-bridge` | **Optional / experimental:** start Mosquitto (`:1883`) for a **generic** broker. Pass **`BACNET2MQTT_*`** / **`MQTT_RPC_*`** env through `stack/.env` to **diy-bacnet-server** for BACnet2MQTT and/or the experimental MQTT RPC gateway ([MQTT integration](howto/mqtt_integration)). |
| `--with-mcp-rag` | **Optional:** include MCP RAG service at http://localhost:8090 (derived from canonical docs and generated docs text). |
| `--mode MODE` | Module mode: `full` (default), `collector`, `model`, `engine`. |
| `--minimal` | DB + BACnet server + bacnet-scraper only. No FDD, weather, or API. Add `--with-grafana` for Grafana. |
| `--verify` | Health checks only: list containers, test DB; exit. Does not start or stop. |
| `--test` | Run tests and exit. With explicit `--mode`, runs that mode only. Without explicit `--mode` (default full), runs matrix: `collector`, `model`, `engine`, `full`. |
| `--build SERVICE ...` | Rebuild and restart only listed services, then exit. Services: `api`, `bacnet-server`, `bacnet-scraper`, `caddy`, `db`, `fdd-loop`, `frontend`, `grafana`, `host-stats`, `mcp-rag`, `mosquitto` (with `--with-mqtt-bridge`), `weather-scraper`. |
| `--build-all` | Rebuild and restart all services; then exit. |
| `--frontend` | Before start: stop frontend container and remove `frontend_node_modules` volume so the next `up` runs a fresh `npm ci`. Use after changing `frontend/package.json`; the frontend service also runs `npm run build` on every start. |
| `--update` | Git pull open-fdd and diy-bacnet-server (sibling), then rebuild and restart (keeps DB). |
| `--maintenance` | Safe Docker prune only (no volume prune). |
| `--reset-grafana` | Wipe Grafana volume and re-apply provisioning. DB and other data retained. |
| `--reset-data` | Delete all sites via API and POST /data-model/reset (testing). |
| `--retention-days N` | TimescaleDB retention in days (default 365). Env: `OFDD_RETENTION_DAYS`. |
| `--log-max-size SIZE` | Docker log max size per file (default `100m`). Env: `OFDD_LOG_MAX_SIZE`. |
| `--log-max-files N` | Docker log max files per container (default 3). Env: `OFDD_LOG_MAX_FILES`. |
| `--install-docker` | Attempt Docker install (Linux) then continue. |
| `--skip-docker-install` | Explicitly skip Docker install (no-op; use with scripts that call bootstrap after install). |
| `--caddy-self-signed` | Self-signed HTTPS for Caddy (`:443`, `:80` → HTTPS): writes certs under `stack/caddy/certs/`, sets `OPENFDD_CADDYFILE` and `OFDD_TRUST_FORWARDED_PROTO=true` in `stack/.env`. |
| `--caddy-tls-cn HOST` | With `--caddy-self-signed`: certificate CN/SAN (default `openfdd.local`). |
| `--caddy-http-only` | Revert to the default HTTP-only Caddyfile on `:80`; removes `OPENFDD_CADDYFILE` from `stack/.env` and sets `OFDD_TRUST_FORWARDED_PROTO=false`. |
| `--no-auth` | Removes auth-related keys from `stack/.env`: **`OFDD_API_KEY`**, Phase 1 keys (**`OFDD_APP_USER`**, **`OFDD_APP_USER_HASH`**, **`OFDD_JWT_SECRET`**, token TTLs), and **`OFDD_BACNET_SERVER_API_KEY`**. Open-FDD API then skips Bearer/JWT enforcement; diy-bacnet-server gets an empty **`BACNET_RPC_API_KEY`** so RPC Bearer middleware is off. |
| `--user NAME` | Phase 1 dashboard user: writes `OFDD_APP_USER`, Argon2 hash, `OFDD_JWT_SECRET`, and token TTLs into `stack/.env` (requires a password — next rows). |
| `--password-file PATH` | Read the Phase 1 password from a file (first line); avoids putting the password on the command line. |
| `--password-stdin` | Read the Phase 1 password from stdin (pipe or redirect into bootstrap; see [Security — Phase 1 examples](security#frontend-and-api-authentication-phase-1) and `bootstrap.sh` header comments). |
| *(env)* | Alternative: set **`OFDD_APP_PASSWORD`** for the Phase 1 password when using `--user`, or use the interactive prompt if neither file nor stdin is used. |

**Bearer tokens and API keys (`stack/.env`):** With a normal bootstrap (no `--no-auth`), secrets live in **`stack/.env`** (gitignored). They are **not** the same token—each service uses the one that matches its role:

| Variable | Consumed by | Role |
|----------|-------------|------|
| **`OFDD_API_KEY`** | **Open-FDD API** | Machine **`Authorization: Bearer`** for REST (Swagger **Authorize**, BACnet scraper → `GET /config`, scripts, agents). |
| **`OFDD_APP_USER`**, **`OFDD_APP_USER_HASH`**, **`OFDD_JWT_SECRET`** (+ TTL keys) | **Open-FDD API** (`/auth/login`, JWT validation) | Dashboard login; the browser keeps a **short-lived JWT** and sends **`Authorization: Bearer`** with that token on API calls—not the dashboard password. |
| **`OFDD_BACNET_SERVER_API_KEY`** | **Open-FDD API** and **bacnet-scraper** (outbound to the gateway) | **`Authorization: Bearer`** on JSON-RPC to **diy-bacnet-server**. Docker Compose passes the **same value** into the gateway container as **`BACNET_RPC_API_KEY`**. When that env is non-empty, the gateway enforces Bearer on RPC routes except **`POST /server_hello`**; when empty, RPC auth is disabled. |

You normally only edit **`stack/.env`**; do not set **`BACNET_RPC_API_KEY`** separately unless you override compose env. Standalone diy-bacnet-server (outside this stack) uses **`BACNET_RPC_API_KEY`** in **its** environment only—see the [diy-bacnet-server README](https://github.com/bbartling/diy-bacnet-server/blob/master/README.md).

Dashboard login and piping passwords into `--user` are covered in more detail (including maintenance one-liners) under **[Security — Phase 1](security#frontend-and-api-authentication-phase-1)**.

To **update** an existing clone: `git pull` then `./scripts/bootstrap.sh`, or `./scripts/bootstrap.sh --update`. Rebuild single services: `./scripts/bootstrap.sh --build api`.

---

## After bootstrap

- **Grafana (if you used `--with-grafana`):** Open http://localhost:3000. A TimescaleDB datasource is provisioned (`openfdd_timescale`); build dashboards with the [Grafana SQL cookbook](howto/grafana_cookbook). If provisioning is wrong, run `./scripts/bootstrap.sh --reset-grafana` (keeps DB data).
- **Minimal mode:** If you used `--minimal`, only DB, BACnet server, and scraper run (plus Grafana **only** if you also passed `--with-grafana`). No API by default; use scraper logs (and Grafana if enabled) to confirm data flow. To add the full stack later, run `./scripts/bootstrap.sh` without `--minimal`.

---

## Next steps

- **[How-to Guides](howto/index)** — Grafana dashboards (optional) and SQL cookbook.
- **[Configuration](configuration)** — Platform config, rule YAML, services that read config from the API.
- **[Security & Caddy](security)** — Basic auth, throttling, TLS.
- **[Appendix: API Reference](appendix/api_reference)** — REST endpoints at a glance; Swagger at http://localhost:8000/docs.

For **BACnet** (discovery and data model): [BACnet](bacnet/index) and [BACnet overview](bacnet/overview). For data modeling and fault rules: [Data modeling](modeling/overview), [Fault rules for HVAC](rules/overview). **Data model export/import (JSON)** works without any AI—you can always export, tag manually or with an external LLM, and import.
