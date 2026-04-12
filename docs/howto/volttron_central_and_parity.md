---
title: VOLTTRON Central and AFDD parity (monorepo)
parent: How-to guides
nav_order: 6
---

# VOLTTRON Central and AFDD parity (monorepo)

This guide is the **recommended path back to parity** with the historical all-in-one Docker AFDD stack, but on **VOLTTRON Central** and this **monorepo** ([bbartling/open-fdd](https://github.com/bbartling/open-fdd)). The old standalone stack repository is **archived** and retained for history only — do not start new deployments there. See the deprecation notice in [bbartling/open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack); active development lives under **`afdd_stack/`** here.

**Mix-and-match rule:** combine **VOLTTRON** (wire protocol, drivers, historian) + **Open-FDD SQL schema** + **`run_fdd_loop()`** (thin agent, systemd timer, or CronJob) + **optional FastAPI + React from source** for Brick/SPARQL/CRUD. **Avoid** running two parallel “stacks” (archived compose + this monorepo) both owning the same database and rules.

---

## Phase 1 — Data plane (one Postgres / Timescale home)

- Start the platform database from the monorepo: `./scripts/bootstrap.sh --compose-db` (or **`--central-lab`**, which includes compose + stubs + schema check + **volttron-docker** clone). See [Getting started](../getting_started).
- Use **one** Postgres (or Timescale) instance for:
  - Open-FDD schema (sites, equipment, points, faults, readings) initialized from `afdd_stack/stack/sql/`.
  - **VOLTTRON SQL historian** tables when you colocate telemetry — configure the historian’s **`tables_def`** (and connection string) so time series land in the same server/database you pass as **`OFDD_DB_DSN`**. Upstream reference: [SQLHistorian](https://volttron.readthedocs.io/en/stable/volttron-api/services/SQLHistorian/README.html).
- **Edges** register to **VOLTTRON Central** per upstream deployment docs; **Central** holds roster and web UI. The **database** remains the integration point for FDD SQL joins (metadata + historian tables).

---

## Phase 2 — Mapping (topics → Open-FDD)

- Install or mount this repo where FDD code runs (host venv with `pip install -e ".[stack]"` or **`PYTHONPATH`** from `./scripts/bootstrap.sh --print-paths`; same layout inside a custom agent container if you bake an image).
- Use **`openfdd_stack.volttron_bridge`** so device / topic naming lines up with **`external_id`**, equipment, and point naming in SQL. Conceptual background: [VOLTTRON gateway and sync](../concepts/volttron_gateway_and_sync), [Brick and VOLTTRON Central target](../concepts/brick_volttron_central_target).

---

## Phase 3 — FDD execution (pick one first)

**A) Thin VOLTTRON agent** on the Central host (or a dedicated “compute” instance): periodic RPC or scheduled behavior calls **`run_fdd_loop()`** with **`OFDD_DB_DSN`** pointing at the shared database. Fits teams that want everything as agents and consistent ops with the rest of the platform.

**B) Alternative:** a **`systemd` timer** or **Kubernetes CronJob** invoking the same Python entrypoint (same loop, same DSN). Fewer moving parts if you do not need VIP for FDD.

Rule authoring and expression patterns: [Expression rule cookbook](../expression_rule_cookbook).

---

## Phase 4 — Modeling / Brick editing (optional UI)

When operators need **UI + SPARQL + CRUD**, run **FastAPI** and **React** **from source** in `afdd_stack/` (as the gateway and security docs describe), not a full resurrection of the old all-in-one compose unless you deliberately need that packaging. See [Getting started](../getting_started), [Data model engineering](data_model_engineering), and [SPARQL cookbook](../modeling/sparql_cookbook).

---

## Phase 5 — Multi-site

- **Central** = roster + web + optionally **one** FDD runner that reads all sites from the database, **or** one FDD runner per edge for fault isolation.
- The **shared database** (and clear site / equipment keys) stays the integration contract between edges, historian, and FDD.

---

## Bootstrap alignment (this repo)

From the **repo root**:

| Goal | Command |
|------|--------|
| Doctor (git, Python, Docker, compose, paths) | `./scripts/bootstrap.sh --doctor` |
| One-shot lab: DB + `VOLTTRON_HOME` stubs + schema verify + clone **volttron-docker** | `./scripts/bootstrap.sh --central-lab` |
| Clone/update official Docker layout | `./scripts/bootstrap.sh --volttron-docker` |
| Minimal Central + SQLHistorian in **`volttron-docker`** (templates, compose, **`psycopg2`**) | `LOCAL_USER_ID=$(id -u) ./scripts/bootstrap.sh --volttron-docker-lab-up` |
| ForwardHistorian auth / logs / “did rows land?” hints on Central | [Edge → Central cheat sheet](edge_forward_historian_to_central) (`--volttron-docker-*`, **`--volttron-docker-forward-proof`**) |
| Local test suite (pytest; optional frontend via env) | `./scripts/bootstrap.sh --test` |

Then build and run **volttron-docker** per [VOLTTRON/volttron-docker](https://github.com/VOLTTRON/volttron-docker): mount the host directory you prepared with **`--volttron-config-stub`** / **`--write-env-defaults`** as **`VOLTTRON_HOME`** so Central state and Open-FDD env survive restarts.

**Compose vs host stubs:** If **`docker-compose.yml`** only mounts **`./configs`** (or similar) and **does not** bind-mount a host directory onto the container’s **`VOLTTRON_HOME`** (commonly **`/home/volttron/.volttron`**), then **`--central-lab`** files under the **host** **`~/.volttron`** are **not** the live config for **`volttron1`**. Align volumes with the [volttron-docker README](https://github.com/VOLTTRON/volttron-docker) (`LOCAL_USER_ID` + host dir → container **`VOLTTRON_HOME`**) before debugging web routes.

**Central UI probes:** Upstream expects **`https://<host>:8443/vc/index.html`** for the Central UI and **`…/admin/login.html`** for admin setup—not every build returns **200** for a bare **`/vc/`** URL; use **`curl -kIL`** on **`/vc/index.html`** when checking from the host.

**`--test`** runs **`pytest`** on `open_fdd/tests` and `afdd_stack/openfdd_stack/tests`. If **`pytest`** is missing, use a venv with **`pip install -e ".[dev]"`** or run once with **`OFDD_BOOTSTRAP_INSTALL_DEV=1 ./scripts/bootstrap.sh --test`**. To also run **eslint**, **`npm run build`** (includes `tsc`), and **Vitest** in `afdd_stack/frontend`, set **`OFDD_BOOTSTRAP_FRONTEND_TEST=1`**. Extra pytest CLI flags: **`OFDD_PYTEST_ARGS`** (space-separated; same caveats as any shell-expanded variable).

---

## See also

- [Getting started](../getting_started) — prerequisites and bootstrap options  
- [Mode-aware runbooks](../operations/mode_aware_runbooks) — collector / model / engine / interface framing  
- [Edge ForwardHistorian → Central (cheat sheet)](edge_forward_historian_to_central) — VIP + serverkey + `vctl auth add` + log hints  
- [openfdd_central_ui README](https://github.com/bbartling/open-fdd/blob/main/afdd_stack/volttron_agents/openfdd_central_ui/README.md) — static Open-FDD UI under `/openfdd/` on Central  
