---
title: Getting Started
nav_order: 3
---

# Getting Started

This page covers **prerequisites** and the **bootstrap script**: how to get the Open-FDD platform running. For configuration, data modeling, and rules, see the [Documentation](index#documentation) index.

---

## Do this to bootstrap

1. **Prerequisites:** **Git** and **Python 3** on the edge host (Linux). **Docker** is optional — only if you want the local **Timescale** container for Open-FDD SQL schema (`--compose-db`).
2. **Clone and run bootstrap** (from repo root):

   ```bash
   git clone https://github.com/bbartling/open-fdd.git
   cd open-fdd
   ./afdd_stack/scripts/bootstrap.sh --help
   ./afdd_stack/scripts/bootstrap.sh --doctor
   ./afdd_stack/scripts/bootstrap.sh --clone-volttron --install-venv
   ```

3. **Optional local database** (faults / sites / points schema + historian-friendly Postgres):

   ```bash
   ./afdd_stack/scripts/bootstrap.sh --compose-db
   ```

Field BACnet, scraping, FDD loop execution, and operator UI are expected on **VOLTTRON / VOLTTRON Central**, not in this compose file. The FastAPI app may still be run **from source** for development (`uvicorn`); it is no longer shipped as a Docker service here.

---

## External Agentic AI (OpenAI-compatible)

Open‑FDD does not embed an LLM. Instead, external AI agents (for example an OpenAI-compatible tool like Open‑Claw) can take advantage of Open‑FDD by calling its APIs:

1. Export the current data model JSON: `GET /data-model/export`
2. Fetch documentation as model context: `GET /model-context/docs` (optionally with `query=...` / keyword retrieval)
3. Import tagged JSON back into the platform: `PUT /data-model/import`

Manual Data Model export/import (JSON) always works without any AI.

See [Open‑Claw integration](openclaw_integration) and [API Reference](appendix/api_reference) for endpoint details.

The optional **MCP RAG** sidecar and **`--with-mcp-rag`** bootstrap flag were **removed**; use **`GET /openapi.json`** / **`/docs`** and **`GET /model-context/docs`** for agents instead.

---

## Prerequisites

- **OS:** Linux for VOLTTRON edge (e.g. Raspberry Pi). Maintainers primarily test on **x86_64** and **ARM64**. Bootstrap shell is not aimed at Windows. Keep the system updated:
  ```bash
  sudo apt update && sudo apt upgrade -y
  ```
- **Docker and Docker Compose:** **Optional** — only for **`--compose-db`** (Timescale + init SQL). See [Docker install](https://docs.docker.com/engine/install/).
- **Python:** Use a venv for monorepo dev tests: `pip install -e ".[dev]"` (see root README).
- **Troubleshooting:** `./afdd_stack/scripts/bootstrap.sh --doctor` checks **git** and **python3**.
- **Git:** To clone the project:
  ```bash
  git clone https://github.com/bbartling/open-fdd.git
  cd open-fdd
  ```
- **BACnet / field data:** Use **VOLTTRON** Platform Driver + historian on the edge. Historical docs for diy-bacnet + scraper may still describe APIs that proxy a gateway when you run the FastAPI app from source.

---

## What the bootstrap script does

`afdd_stack/scripts/bootstrap.sh` (run from the **repo root**):

1. **`--clone-volttron`** — clone or update [Eclipse VOLTTRON](https://github.com/eclipse-volttron/volttron) (`OFDD_VOLTTRON_DIR`, branch `releases/9.x` by default).
2. **`--install-venv`** — `python3 -m venv` under the VOLTTRON tree and `pip install -e` VOLTTRON.
3. **`--compose-db`** — optional `docker compose … up -d db` for Timescale + `stack/sql` init.
4. **`--print-paths`** — prints `PYTHONPATH` so agents can `import openfdd_stack`.

**Bootstrap options:** Run `./afdd_stack/scripts/bootstrap.sh --help`. The old “one command brings up API + Caddy + BACnet in Docker” flow is **removed**; see **`afdd_stack/legacy/README.md`** for what changed.

**Open-FDD API from source:** If you run **`uvicorn`** for local development, configure secrets and auth in **`afdd_stack/stack/.env`** as described under **[Security — authentication](security#frontend-and-api-authentication)** (API keys, JWT, dashboard user). That file is **not** populated by the slim bootstrap; compose no longer starts the API container.

**Optional Grafana:** With Docker available, from `afdd_stack/stack/` you can start the **`grafana`** profile (see compose file comments) for dashboards against the same Postgres/Timescale host; use the [Grafana SQL cookbook](howto/grafana_cookbook).

**VOLTTRON Central / edge UI:** Use upstream VOLTTRON and Central docs for remote access, TLS, and operator UI — not Caddy from this repo.

---

## After bootstrap

- **Database:** With **`--compose-db`**, Postgres listens on the host port defined in compose (see `afdd_stack/stack/docker-compose.yml`). Apply VOLTTRON SQL historian **`tables_def`** against the same server if you colocate historian tables with Open-FDD schema; keep backups and migrations explicit.
- **Agents:** Point **`PYTHONPATH`** at this repo (**`--print-paths`**) when packaging Open-FDD logic as VOLTTRON agents.

---

## Next steps

- **[How-to Guides](howto/index)** — Grafana (optional) and SQL cookbook.
- **[Configuration](configuration)** — Platform config, rule YAML.
- **[Security](security)** — API keys and JWT when running the FastAPI app from source.
- **[Appendix: API Reference](appendix/api_reference)** — REST endpoints for agents and tooling.
- **[VOLTTRON gateway and sync](concepts/volttron_gateway_and_sync)** — how field data and SQL fit together.

For data modeling and fault rules: [Data modeling](modeling/overview), [Fault rules for HVAC](rules/overview). **Data model export/import (JSON)** works without any AI—you can always export, tag manually or with an external LLM, and import.
