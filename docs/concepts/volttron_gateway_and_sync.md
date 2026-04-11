---
title: VOLTTRON gateway, FastAPI, and data-model sync
parent: Concepts
nav_order: 5
---

# VOLTTRON gateway, FastAPI, and data-model sync

This page is the **buildable** version of the layered stack: **each site’s VOLTTRON owns all field protocols** (BACnet, Modbus, etc., **only inside VOLTTRON**), **ZMQ** VIP / pub-sub on the VOLTTRON bus, and the [SQL historian](https://volttron.readthedocs.io/en/stable/volttron-api/services/SQLHistorian/README.html) (optional **TimescaleDB**). **Open-F-DD does not speak those wires**; it keeps the **semantic layer, CRUD, SPARQL, and the React modeling UI** when you run FastAPI/React, and consumes **SQL** for FDD. It also answers: **can scripts + cron replace “always-on” sync?**

**Docker in this repo:** `afdd_stack/stack/docker-compose.yml` runs **Postgres/TimescaleDB** (and optional Grafana or Mosquitto profiles) only. It does **not** start the Open-F-DD API, Caddy, React, or **any** field-bus gateway; use **site VOLTTRON** and **VOLTTRON Central** (or your own process manager) for ingest and fleet UI.

For a **long-range target** where **Brick is canonical on VOLTTRON or Central** and the **standalone FastAPI service is intentionally retired**, see **[Target vision — Brick on VOLTTRON, Central, no FastAPI](brick_volttron_central_target)** (that path replaces FastAPI with explicit alternatives—it does not remove the need for an API surface).

---

## Layered architecture (what to actually run)

```text
  Building LAN (site VOLTTRON)              App tier (same DC, VPC, or host)
  ----------------------------              ---------------------------------

  VOLTTRON 9 + ZMQ VIP / pub-sub  ------>  Postgres / Timescale
  Field drivers (BACnet, Modbus, …        (historian tables + Open-F-DD schema)
   only inside VOLTTRON)

  Historian / ETL agents          ------>  optional FastAPI + React
                                           (CRUD, SPARQL, TTL, jobs)

  Custom agents (alarms, FDD, CSV) ------>  same SQL or HTTP to API
```

Solid arrows: data flow. **Browsers and LLM tools** should use **FastAPI**, not raw historian SQL.

**Rule of thumb:** anything a **browser** or **LLM tool** touches should go through **FastAPI** (or a future thin gateway that exposes the same contracts). **VOLTTRON** should not become your public HTTP server for SPARQL and CRUD.

---

## Where FastAPI is still required (or strongly advised)

| Capability | Why not “agents only” |
|------------|------------------------|
| **SPARQL** (`POST /data-model/sparql`) | Needs the **unified graph** (rdflib), request concurrency, and a stable contract for the React **Data Model Testing** and automation. |
| **CRUD** (sites, equipment, points, import or export) | Transactional **Postgres** updates, validation, and orchestration already live here. |
| **Serialize or reset graph** (`POST /data-model/serialize`, `POST /data-model/reset`) | The in-memory graph and **TTL file** lifecycle are owned by the API process today. |
| **Auth, websockets, jobs, downloads** | Same process boundary; replacing it means reimplementing security and UX contracts. |

In a **VOLTTRON-first** deployment, **all** field BACnet/Modbus traffic stays in **VOLTTRON** on the site LAN; keep **FastAPI + React** (from source) when you need **CRUD, SPARQL, and the modeling UI**, and run **FDD** as **agents** or batch jobs against SQL. Default **Compose** in this repo ships **no** field-bus or scraper containers — see [Modular architecture](../modular_architecture), **[Site VOLTTRON and the data plane (ZMQ)](site_volttron_data_plane)**, and **`afdd_stack/legacy/README.md`**.

---

## Can cron + scripts maintain data-model sync?

**Yes, for part of the problem.** Treat sync as **two different pipelines**:

### 1) File sync (TTL on disk, backups, GitOps)

The platform already runs a **background thread** that writes `config/data_model.ttl` on an interval (`graph_sync_interval_min` in settings; see [System overview](../overview)). **Cron is redundant** for “write TTL occasionally” unless you want **explicit** checkpoints after batch jobs.

Use **cron or systemd timers** when:

- You want a **guaranteed** serialize after an external batch (ETL, Ansible, OpenClaw) finishes.
- The API process is **always up** and you only need to hit **`POST /data-model/serialize`**.

Repo helper: `afdd_stack/scripts/cron_ttl_serialize.sh` (see script header for env vars).

### 2) Semantic truth (Brick graph matches Postgres)

If **only** the FastAPI process updates the DB through CRUD, the in-memory graph and TTL stay aligned without cron.

If a **separate writer** (VOLTTRON agent, dbt, script) updates **Postgres** tables that back Brick (sites, equipment, points metadata), the **in-memory RDF graph** in the API process can be **stale** until you:

- **`POST /data-model/reset`** — repopulates **Brick from DB only**, rewrites TTL, and clears **non-Brick** triples that the API had loaded (see the route docstring in `openfdd_stack/platform/api/data_model.py`). **BACnet RDF is not** produced by Open-F-DD in the default architecture.
- Or route topology changes through the **existing REST import or CRUD** so the graph updates inside the API.

**Cron alone cannot fix stale in-memory state** if nothing calls the API or restarts the process; you need at least **one** of: HTTP call to reset or serialize, **shared process** that owns the graph, or a **long-term refactor** (e.g. sidecar triple store).

### 3) Time-series values (live readings)

Historian topics (`devices/...`) are **not** the same as Brick TTL. Sync **readings** into Open-F-DD’s `timeseries_readings` (or future merged schema) with a **small ETL agent** on a schedule or on pub/sub. That is **orthogonal** to TTL serialize cron.

---

## VOLTTRON Central

Use **[VOLTTRON Central](https://volttron.readthedocs.io/)** when you need **multi-instance** operations and health views. Do **not** treat it as the primary **energy engineering** or **SPARQL** UI; keep those on **Open-F-DD’s React + FastAPI**.

---

## Practical deployment profiles

| Profile | Edge | App tier |
|---------|------|----------|
| **A — Default monorepo compose** | VOLTTRON (+ historian) on edge | Postgres/Timescale (+ optional Grafana); FastAPI/React **from source** when needed |
| **B — VOLTTRON field, Open-FDD brain** | VOLTTRON historian + ETL to app DB | FastAPI for model/SPARQL; FDD via agents; cron or HTTP for serialize/reset after bulk DB writes |
| **C — Fleet** | Many Pis like profile B | Optional Central + one modeling API per site or shared read models |
| **D — Legacy Docker stack** | **Removed** diy-bacnet / scraper compose (fork only) | Do **not** use for new BACnet ingest — **legacy** README |

---

## References

- VOLTTRON **Historian framework** and **platform historian** identity: [Historian framework](https://volttron.readthedocs.io/en/main/agent-framework/historian-agents/historian-framework.html).
- **SQL historian** and **TimescaleDB** connection params: [SQLHistorian](https://volttron.readthedocs.io/en/stable/volttron-api/services/SQLHistorian/README.html).
- Lab pattern for VOLTTRON 9 on a Pi: [vibe_code_apps_6](https://github.com/bbartling/py-bacnet-stacks-playground/tree/develop/vibe_code_apps_6) in **py-bacnet-stacks-playground**.
