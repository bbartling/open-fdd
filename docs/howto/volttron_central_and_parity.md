---
title: VOLTTRON Central and AFDD parity (monorepo)
parent: How-to guides
nav_order: 6
---

# VOLTTRON Central and AFDD parity (monorepo)

This guide is the **recommended path back to parity** with the historical all-in-one Docker AFDD stack, but on **VOLTTRON Central** and this **monorepo** ([bbartling/open-fdd](https://github.com/bbartling/open-fdd)). The old standalone stack repository is **archived** and retained for history only — do not start new deployments there. See the deprecation notice in [bbartling/open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack); active development lives under **`afdd_stack/`** here.

**Mix-and-match rule:** combine **VOLTTRON** (wire protocol, drivers, historian) + **Open-F-DD SQL schema** + **`run_fdd_loop()`** (thin agent, systemd timer, or CronJob) + **optional FastAPI + React from source** for Brick/SPARQL/CRUD. **Avoid** running two parallel “stacks” (archived compose + this monorepo) both owning the same database and rules.

---

## Phase 1 — Data plane (one Postgres / Timescale home)

- Start the platform database from the monorepo: `./afdd_stack/scripts/bootstrap.sh --compose-db` (or **`--central-lab`**, which includes compose + stubs + schema check + **volttron-docker** clone). See [Getting started](../getting_started).
- Use **one** Postgres (or Timescale) instance for:
  - Open-F-DD schema (sites, equipment, points, faults, readings) initialized from `afdd_stack/stack/sql/`.
  - **VOLTTRON SQL historian** tables when you colocate telemetry — configure the historian’s **`tables_def`** (and connection string) so time series land in the same server/database you pass as **`OFDD_DB_DSN`**. Upstream reference: [SQLHistorian](https://volttron.readthedocs.io/en/stable/volttron-api/services/SQLHistorian/README.html).
- **Edges** register to **VOLTTRON Central** per upstream deployment docs; **Central** holds roster and web UI. The **database** remains the integration point for FDD SQL joins (metadata + historian tables).

---

## Phase 2 — Mapping (topics → Open-F-DD)

- Install or mount this repo where FDD code runs (host venv with `pip install -e ".[stack]"` or **`PYTHONPATH`** from `./afdd_stack/scripts/bootstrap.sh --print-paths`; same layout inside a custom agent container if you bake an image).
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
| Doctor (git, Python, Docker, compose, paths) | `./afdd_stack/scripts/bootstrap.sh --doctor` |
| One-shot lab: DB + `VOLTTRON_HOME` stubs + schema verify + clone **volttron-docker** | `./afdd_stack/scripts/bootstrap.sh --central-lab` |
| Clone/update official Docker layout | `./afdd_stack/scripts/bootstrap.sh --volttron-docker` |
| Local test suite (pytest; optional frontend via env) | `./afdd_stack/scripts/bootstrap.sh --test` |

Then build and run **volttron-docker** per [VOLTTRON/volttron-docker](https://github.com/VOLTTRON/volttron-docker): mount the host directory you prepared with **`--volttron-config-stub`** / **`--write-env-defaults`** as **`VOLTTRON_HOME`** so Central state and Open-F-DD env survive restarts.

**`--test`** runs **`pytest`** on `open_fdd/tests` and `afdd_stack/openfdd_stack/tests`. If **`pytest`** is missing, use a venv with **`pip install -e ".[dev]"`** or run once with **`OFDD_BOOTSTRAP_INSTALL_DEV=1 ./afdd_stack/scripts/bootstrap.sh --test`**. To also run **eslint**, **`npm run build`** (includes `tsc`), and **Vitest** in `afdd_stack/frontend`, set **`OFDD_BOOTSTRAP_FRONTEND_TEST=1`**. Extra pytest CLI flags: **`OFDD_PYTEST_ARGS`** (space-separated; same caveats as any shell-expanded variable).

---

## See also

- [Getting started](../getting_started) — prerequisites and bootstrap options  
- [Mode-aware runbooks](../operations/mode_aware_runbooks) — collector / model / engine / interface framing  
- [openfdd_central_ui README](https://github.com/bbartling/open-fdd/blob/main/afdd_stack/volttron_agents/openfdd_central_ui/README.md) — static Open-F-DD UI under `/openfdd/` on Central  
