---
title: Agent architecture
parent: External agents
nav_order: 1
---

# Open-FDD external multi-agent architecture

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

Open-FDD is a **deterministic Rust edge runtime**. Assistance is provided by **external orchestrators** (Codex CLI, Cursor, OpenClaw) using git, safe scripts, JWT REST, and optional `openfdd-mcp` — not by embedding chat or LLM runtimes in the dashboard.

## Layered model

```text
┌─────────────────────────────────────────────────────────────┐
│  External operator (Codex CLI / Cursor / OpenClaw / MCP host) │
│  - plans, edits docs/code, opens PRs                         │
│  - runs safe scripts (bootstrap, validate, smoke)              │
│  - uses MCP or REST with integrator JWT                      │
└───────────────────────────┬─────────────────────────────────┘
                            │ git, bash, curl+JWT (127.0.0.1)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Open-FDD container stack (deterministic)                    │
│  central (API/FDD) │ ui (Caddy) │ fieldbus │ mqtt (broker)   │
│  historian · DataFusion FDD · drivers · reports              │
└───────────────────────────┬─────────────────────────────────┘
                            │ fieldbus: BACnet/IP (OT LAN) → MQTTS
                            ▼
                     Field devices & stations
```

## Responsibilities

### Rust edge (product)

- JWT auth and RBAC
- OT drivers, historian, DataFusion FDD, reports
- Optional `openfdd-mcp` binary (stdio) — operator-controlled

### External agents (not product)

- Edit docs, scripts, tests in git
- Run safe lifecycle scripts
- Connect via MCP or REST from **outside** the dashboard
- Never imply Open-FDD ships a built-in chatbot

## Related

- [openfdd-agent-current-standing.md](openfdd-agent-current-standing.md)
- [model-routing.md](model-routing.md)
- [../examples/external-agents.md](../examples/external-agents.md)
