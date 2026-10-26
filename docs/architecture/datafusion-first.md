---
title: DataFusion-first (historical)
parent: Architecture
nav_order: 10
---

# DataFusion-first policy (historical)

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

> **SUPERSEDED. historical/non-executable.** Product path is Timescale-only ([ADR-010](adr-010-timescale-hard-cutover.md)), `architecture_epoch: portal-timescale-v1`. Soft-OPEN ≠ FQ. Do not add DataFusion because this page still names it.

The tables under this heading record the retired engine. They are not requirements.


For tabular building telemetry computation in the **product**:

> If the operation can reasonably be expressed as DataFusion SQL, it belongs in DataFusion SQL in central.

## Product (required)

| Layer | Owns |
|-------|------|
| Central + `sql_rules/` + DataFusion | FDD, Overview/RCx analytics, exports of computed values |
| React SPA (`frontend/web`) | Rendering, interaction, presentation-only formatting — **no** engineering recomputation |
| Mosquitto + fieldbus | Transport / edge ingest |

**Forbidden in product** (any request path, job, export, sidecar, or opt-in flag):

- Python / pandas / Pyodide / WASM Python / subprocess bridges for FDD or analytics
- Silent pandas FDD fallback when DataFusion fails
- `OPENFDD_ALLOW_PANDAS_FDD` (retired — must not reappear in product)
- Millions of raw rows into the browser for client-side downsample before fault math
- A second React app for WattLab/EnergyPlus (keep Export handoff in the united UI)

## External tooling (allowed outside the product)

| Class | When |
|-------|------|
| PyPI oracle | Independent `open_fdd.rules` / cookbook parity vs SQL |
| Offline helpers | WattLab/ECM tools consuming authenticated exports like any client |
| Test harnesses | Python drivers against a Python-free SUT |

Do **not** delete the pandas cookbook because production uses SQL. Do **not** recreate deleted `frontend/web/app/*.py` paths.

## Production FDD today

Canonical path: `sql_rules/` + `crates/fdd_rules` + `POST /api/fdd/run`.  
UI: **one** React SPA (`frontend/web` → `openfdd-web`).

See SoT: [`openfdd_agent_spec/ARCHITECTURE.md`](../../openfdd_agent_spec/ARCHITECTURE.md) · [ownership inventory](compute_boundary_ownership.yaml) · [Rule Cookbook](../rules/cookbook/).
