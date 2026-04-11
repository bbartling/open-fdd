---
title: Mode-aware runbooks
parent: Operations
nav_order: 6
---

# Mode-aware runbooks

The historical **`./scripts/bootstrap.sh --mode {collector|model|engine|full}`** flow matched a **full Docker Compose** stack (BACnet scraper, API, Caddy, `fdd-loop`, etc.). That stack is **no longer** the default in this monorepo.

## Current commands

```bash
./afdd_stack/scripts/bootstrap.sh --doctor
./afdd_stack/scripts/bootstrap.sh --central-lab
./afdd_stack/scripts/bootstrap.sh --compose-db    # optional local Postgres/Timescale
./afdd_stack/scripts/bootstrap.sh --print-paths   # PYTHONPATH for openfdd_stack agents
```

Then follow **VOLTTRON** and **VOLTTRON Central** docs on the edge host. Use **FastAPI** (**`uvicorn`**) and the **React** app from source when you need REST/SPARQL/modeling.

## Tests (monorepo)

From the repo root with a dev venv:

```bash
pip install -e ".[dev]"
python -m pytest
```

## Legacy Docker modes

If you run a **fork** or custom compose that still exposes **`--mode`**, treat those runbooks as **deployment-specific**. Upstream removal details: **`afdd_stack/legacy/README.md`**.
