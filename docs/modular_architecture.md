---
title: Modular Architecture
nav_order: 4
---

# Modular Architecture

Open-FDD separates concerns into **collector**, **model**, **engine**, and **interface** modules. The **default bootstrap** in this repo is **VOLTTRON-first** (`./scripts/bootstrap.sh`) and no longer maps those modules to **`docker compose` services** the way the old full stack did.

## Module contracts (conceptual)

| Module | Concern | Typical runtime today |
|--------|---------|------------------------|
| **Collector** | Field protocols + historian (**ZMQ** bus in VOLTTRON, not RabbitMQ here) | **Per-site VOLTTRON** platform driver + SQL historian; optional ETL into `timeseries_readings` |
| **Model** | Brick / data-model CRUD, SPARQL, TTL | **FastAPI** (+ optional React) **from source** when you need the semantic layer |
| **Engine** | Pandas / YAML FDD execution | **VOLTTRON agents** or **`open_fdd.engine`** on DataFrames; historical **`fdd-loop`** container removed from default compose |
| **Interface** | REST, OpenClaw-style HTTP, export/import | **FastAPI** when running **`uvicorn`**; **VOLTTRON Central** for fleet/edge UI |

## Legacy Docker mode matrix

The one-command **`./scripts/bootstrap.sh --mode …`** matrix applied when Compose shipped **`api`**, **`bacnet-scraper`**, **`fdd-loop`**, **Caddy**, etc. That stack is **removed** from the default `afdd_stack/stack/docker-compose.yml`. For a concise list of what disappeared and how to run **SQL-only** compose, see **`afdd_stack/legacy/README.md`**.

If you maintain a **private fork** or custom compose that restores those services, you can still think in terms of:

- **Collector slice:** DB + **site VOLTTRON** historians (SQL) + topic mapping  
- **Model slice:** DB + API + frontend + reverse proxy  
- **Engine slice:** DB + scheduled FDD + optional weather  

… but upstream Open-FDD docs assume **VOLTTRON** owns the collector slice for new deployments.

## Feature coverage (conceptual)

| Feature | Collector (VOLTTRON) | Model (FastAPI+React) | Engine (agents / library) |
|---------|--------------------|------------------------|---------------------------|
| Time-series ingest | yes (historian / ETL) | no | reads DB or frames |
| CRUD + SPARQL | no | yes (when API up) | no |
| React / Central UI | Central (edge) | dev server / build | — |
| FDD rules | via agents | via API/jobs if enabled | `RuleRunner` |

## Migration stance

The repository stays a **single codebase**: **`open_fdd`** on PyPI, **`openfdd_stack`** for platform and VOLTTRON helpers. Module boundaries help you choose **which processes to run** without implying every process still has a matching container in this repo.

## External IoT / “we already have collection + modeling”

If another system owns **ingestion** and **semantic modeling**, use **`open_fdd.engine`** on **pandas** with the **same YAML** as the platform, or wire a thin agent to SQL. See [Engine-only deployment and external IoT pipelines](howto/engine_only_iot). For **`openfdd_engine`** vs **`open_fdd.engine`**, see [The optional openfdd-engine package](howto/openfdd_engine).
