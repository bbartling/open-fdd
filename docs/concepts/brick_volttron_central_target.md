---
title: Target vision — Brick on VOLTTRON, Central as hub, no FastAPI
parent: Concepts
nav_order: 6
---

# Target vision — Brick on VOLTTRON, Central as hub, no FastAPI

This page captures a **long-range architecture** some deployments want: **Open-FDD runs as a layer across VOLTTRON (and optionally VOLTTRON Central)**, the **canonical model is Brick**, and the **standalone FastAPI service goes away**. Lab folders like **vibe_code_apps_7** stay **experiments and education**; they are not the shipping product, but they inform it.

---

## What this vision is really asking for

| Stated goal | Translation in engineering terms |
|-------------|-----------------------------------|
| Layer on **VOLTTRON Central** | One **control plane** (instance registry, health, optional plots) plus **shared storage** (often **PostgreSQL or Timescale** behind historians on each instance). Open-FDD logic becomes **agents + jobs + DB schema**, not a second “platform” beside VOLTTRON. |
| **“Just a Brick model”** | **Brick (and friends) is the only semantic schema** you commit to for topology and point identity. You **stop maintaining a parallel RDF universe** (e.g. separate BACnet RDF blobs) **unless** you still need discovery artifacts—in which case they are **import steps** into Brick, not a second permanent graph. |
| **Get rid of FastAPI** | You **remove the current `afdd_stack` FastAPI process** as the public API. **Something else** must still provide: **authenticated CRUD**, **queries** (SPARQL or SQL views over Brick), **file or export contracts**, and **any browser or LLM integration**. That “something” is **new work**—it does not appear for free inside Central’s UI. |

---

## Reality check — VOLTTRON Central is not a Brick server

[VOLTTRON Central](https://volttron.readthedocs.io/) and the **platform historian** are built around **topics and time series** (`topics`, `data`, metadata)—not around **Brick classes, relationships, and SPARQL**. So “Open-FDD as a layer on top” means:

1. **Brick lives in your own tables** (or in a small triple store) in **PostgreSQL** (or attached to Central’s DB strategy), **designed by you**.
2. **Historian** continues to own **high-volume samples**; you **join** or **map** historian topics to **Brick `Point`** identities via stable IDs you control.
3. **Open-FDD’s rules engine** still needs **pandas-shaped** inputs: you **materialize** frames from historian plus Brick metadata in an **agent or scheduled job**, not by magic from Central alone.

**Central** is valuable for **many instances** and **operator visibility**; it is **not** a replacement for a **semantic application server** unless you build that server elsewhere.

---

## If FastAPI goes away, what replaces it?

You are not eliminating **HTTP and business logic**—you are **moving** them. Realistic replacements:

| Option | Role of “API” | Pros | Cons |
|--------|----------------|------|------|
| **A. VOLTTRON agents + VIP RPC** | UIs or scripts call **`vctl`** / RPC from a **thin local gateway** | No FastAPI container; logic colocated with data | **No first-class browser REST** unless you add another layer |
| **B. One minimal HTTP agent** (FastAPI, Starlette, or Flask **inside** a single agent) | Same routes as today, smaller footprint | Reuse OpenAPI patterns; one process | Still “an HTTP stack”—just not the monorepo’s current layout |
| **C. SQL + PostgREST or Hasura** | **Brick tables** exposed as REST or GraphQL | Very little custom server code | SPARQL and complex graph rules need **SQL views** or a **sidecar** |
| **D. Static React + BFF agent** | Agent serves static build + a few JSON endpoints | Feels like “no big platform” | Same as B, different packaging |

**Deleting FastAPI without picking A–D** leaves **no supported path** for the React app and OpenClaw-style automation described elsewhere in this repo.

---

## “Brick only” and the rules engine

The **PyPI `open-fdd` engine** is **YAML + pandas**, not RDF at runtime. A **Brick-only** platform still needs a **deterministic bridge**: Brick metadata + historian samples → **DataFrame columns** the rules expect. That bridge belongs in **VOLTTRON agents** (or DB views + a small runner), not in Central’s stock UI.

---

## Code landing zone (monorepo)

The first importable slice lives in Python package **`openfdd_stack.volttron_bridge`** (`afdd_stack/openfdd_stack/volttron_bridge/`): **device topic parsing**, **flattening** platform-driver style dicts, **mapping** flattens to Open-FDD ``external_id`` keys for engine rows, and **DB lookup** of points for an equipment name that matches a VOLTTRON driver device. Agents on the Pi can depend on this package once it is installed from the monorepo. Unit tests: ``afdd_stack/openfdd_stack/tests/platform/test_volttron_bridge.py``.

---

## Suggested phased path (if the org commits to this)

1. **Freeze the product split** — Edge = VOLTTRON + historian; **Brick + alarms + FDD metadata** = **Postgres schema** you own (can live next to historian DB with clear boundaries).
2. **Stop growing BACnet-as-RDF** — Treat BACnet discovery as **ingest into Brick + external_id**, align with [modular architecture](../modular_architecture) “model” concerns.
3. **Extract** the smallest set of routes you still need (export or import, one SPARQL or SQL path) into **option B or C** above.
4. **Retire** the monorepo FastAPI service only when **feature parity** for your chosen users (modeling, energy, FDD runs) exists on the new layer.
5. **Central last** — Add **VOLTTRON Central** when **multiple** instances justify it; it is **optional** for a single-building Brick + historian deployment.

---

## How this relates to other docs

- **[VOLTTRON gateway, FastAPI, and data-model sync](volttron_gateway_and_sync)** describes the **practical near-term** split: VOLTTRON on the wire, **FastAPI** for graph and SPARQL until a deliberate cutover.
- This page is the **target-state** counterpoint: **same Brick truth**, **different process boundary**, **no long-lived FastAPI** once replacements exist.

---

## Bottom line

- **Yes**, you can aim for **Open-FDD conceptual stack** (Brick + engine + alarms) **running across VOLTTRON and Central’s ecosystem**, with **vibe_code_apps_7-style work** kept as **education only**.
- **No**, you cannot **delete FastAPI** today without **replacing** its responsibilities; **Central does not subsume** SPARQL, CRUD, and the current React contract by itself.
- **“Just Brick”** is a **schema and product simplification**, not a smaller amount of **software**—it is often **more discipline** in one graph instead of two.
