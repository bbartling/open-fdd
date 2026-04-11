---
title: Getting Started
nav_order: 3
---

# Getting Started

This page covers **prerequisites** and the **bootstrap script**: how to get the Open-FDD platform running. For configuration, data modeling, and rules, see the [Documentation](index#documentation) index.

---

## Do this to bootstrap

1. **Prerequisites:** **Git** and **Docker** (including Compose v2). **Python 3** on the host for monorepo dev, **`--smoke-fdd-loop`**, and tooling — the bootstrap script no longer installs VOLTTRON in a host venv; use **[volttron-docker](https://github.com/VOLTTRON/volttron-docker)** for the platform.
2. **Clone and run bootstrap** (from repo root):

   ```bash
   git clone https://github.com/bbartling/open-fdd.git
   cd open-fdd
   ./afdd_stack/scripts/bootstrap.sh --help
   ./afdd_stack/scripts/bootstrap.sh --doctor
   ```

   **VOLTTRON Central via Docker (when you have Docker):**

   ```bash
   ./afdd_stack/scripts/bootstrap.sh --volttron-docker
   cd "${OFDD_VOLTTRON_DOCKER_DIR:-$HOME/volttron-docker}"
   # Build the image and run docker compose per that repository's README.
   ```

   **One-shot lab (Timescale + stubs + clone volttron-docker):**

   ```bash
   ./afdd_stack/scripts/bootstrap.sh --central-lab
   ```

   **Run the test suite (like the legacy stack’s `--test`):**

   ```bash
   ./afdd_stack/scripts/bootstrap.sh --test
   # If pytest is missing: OFDD_BOOTSTRAP_INSTALL_DEV=1 ./afdd_stack/scripts/bootstrap.sh --test
   # Optional: eslint + tsc + vitest in afdd_stack/frontend
   # OFDD_BOOTSTRAP_FRONTEND_TEST=1 ./afdd_stack/scripts/bootstrap.sh --test
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
- **Docker and Docker Compose:** **Optional** for **`--compose-db`** (Timescale + init SQL) and **recommended** for **[volttron-docker](https://github.com/VOLTTRON/volttron-docker)** (VOLTTRON Central in a container). See [Docker install](https://docs.docker.com/engine/install/).
- **Python:** Use a venv for monorepo dev tests: `pip install -e ".[dev]"` (see root README). For **`--smoke-fdd-loop`**, install **`pip install -e ".[stack]"`** in that venv or set **`PYTHONPATH`** from **`--print-paths`**.
- **Troubleshooting:** `./afdd_stack/scripts/bootstrap.sh --doctor` checks **git**, **python3**, **Docker**, and **Compose**.
- **Git:** To clone the project:
  ```bash
  git clone https://github.com/bbartling/open-fdd.git
  cd open-fdd
  ```
- **BACnet / field data:** Use **VOLTTRON** Platform Driver + historian on the edge. Historical docs for diy-bacnet + scraper may still describe APIs that proxy a gateway when you run the FastAPI app from source.

---

## What the bootstrap script does

`afdd_stack/scripts/bootstrap.sh` (run from the **repo root**):

1. **`--central-lab`** — runs **`--compose-db`**, waits for Postgres, writes **`$VOLTTRON_HOME`** stubs (**`--volttron-config-stub`**, **`--write-env-defaults`**, **`--write-logrotate`**), verifies the FDD schema, then **`--volttron-docker`** (clone/update **volttron-docker**). Afterward, build the image and **`docker compose up`** from **`$HOME/volttron-docker`** (see that repo’s README).
2. **`--volttron-docker`** (alias **`--clone-volttron-docker`**) — clone or update **[volttron-docker](https://github.com/VOLTTRON/volttron-docker)** into **`OFDD_VOLTTRON_DOCKER_DIR`** (default **`$HOME/volttron-docker`**).
3. **`--compose-db`** — optional `docker compose … up -d db` for Timescale + `stack/sql` init.
4. **`--print-paths`** — prints `PYTHONPATH` so host tools can `import openfdd_stack`.
5. **`--doctor`** — checks **git**, **python3**, **docker**, **docker compose**, and the volttron-docker checkout path.
6. **`--test`** — runs **`pytest`** on `open_fdd/tests` and `afdd_stack/openfdd_stack/tests` from the repo root. Set **`OFDD_BOOTSTRAP_INSTALL_DEV=1`** for a one-shot **`pip install -e ".[dev]"`** before pytest. Set **`OFDD_BOOTSTRAP_FRONTEND_TEST=1`** to also run **`npm ci`**, **`npm run lint`**, **`npm run build`**, and **`npm run test`** under **`afdd_stack/frontend`**. Optional **`OFDD_PYTEST_ARGS`** adds extra pytest flags (shell word-splitting applies).

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
- **[VOLTTRON Central and AFDD parity (monorepo)](howto/volttron_central_and_parity)** — phased plan (one DB, mapping, FDD runner, Brick UI, multi-site) aligned with Central + **volttron-docker**.

For data modeling and fault rules: [Data modeling](modeling/overview), [Fault rules for HVAC](rules/overview). **Data model export/import (JSON)** works without any AI—you can always export, tag manually or with an external LLM, and import.
