---
title: Agent runtime status
parent: External agents
nav_order: 2
---

# Agent runtime status (3.2.x)

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

## Shipped in product

| Item | State |
|------|-------|
| Runtime | Container stack: `openfdd-central` + `openfdd-web` + `openfdd-fieldbus` + `openfdd-mqtt` |
| Images | `ghcr.io/bbartling/openfdd-{central,ui,fieldbus,mqtt,mcp}` |
| Services | `central` (API/FDD), `ui` (Caddy), `fieldbus` (BACnet→MQTTS), `mqtt` (broker) |
| Auth | JWT + RBAC |
| Historian / FDD | Arrow + DataFusion SQL |
| Agent HTTP | `GET /api/agent/tools`, `GET /api/agent/config` |
| MCP | `openfdd-mcp` stdio (optional, external) |
| Embedded chatbot | **Removed** — use external MCP/REST |

## External orchestration

| Role | Tooling |
|------|---------|
| Runtime | Open-FDD container stack only |
| Development / ops | Codex CLI, Cursor, OpenClaw (LAN) |
| MCP | `openfdd-mcp` with JWT |

## Legacy (do not use)

| Signal | Interpretation |
|--------|----------------|
| `POST /api/agent/chat` | Removed |
| Cursor SDK relay / `CURSOR_API_KEY` in edge | Removed |
| In-dashboard Agent chat panel | Removed |
| Python `openfdd-mcp-rag` | Archived |

## Related

- [openfdd-agent-architecture.md](openfdd-agent-architecture.md)
- [openfdd-mcp-tool-contract.md](openfdd-mcp-tool-contract.md)
