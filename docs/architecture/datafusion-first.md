---
title: DataFusion-first policy
parent: Architecture
nav_order: 10
---

# DataFusion-first policy

**Status:** **active product contract** (Wave J Stage A, 2026-09-08). Supersedes the 2026-07-25 “target / PR2+” wording below where they conflict.

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
