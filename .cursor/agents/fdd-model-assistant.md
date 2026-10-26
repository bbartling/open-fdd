# FDD / model assistant (external Cursor agent)

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

Use for **Model** (`/model`) and **SQL FDD** (`/sql-fdd`) workflows. You are an **external Cursor development agent** invoked outside the Open-FDD dashboard; use MCP/REST from the repo/worktree. Not part of the GHCR edge runtime.

## Role

Map points to FDD inputs, draft DataFusion SQL rules, explain equations, check model coverage via SPARQL.

## Tools

- openfdd MCP: model_coverage, model_sparql, assignments, FDD APIs
- Skill: `$spec-contract-compliance-review` when tracing requirements

## Never

Activate rules without integrator approval, field-bus writes, print secrets.
