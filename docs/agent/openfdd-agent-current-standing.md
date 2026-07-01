---
title: Agent runtime status
parent: External agents
nav_order: 2
---

# Agent runtime status (3.2.x)

## Shipped in product

| Item | State |
|------|-------|
| Runtime | Rust `openfdd-edge` + React dashboard |
| Image | `ghcr.io/bbartling/openfdd-edge-rust` |
| Services | `openfdd-bridge`, `openfdd-commission`, `openfdd-haystack-gateway` |
| Auth | JWT + RBAC |
| Historian / FDD | Arrow + DataFusion SQL |
| Agent HTTP | `GET /api/agent/tools`, `GET /api/agent/config` |
| MCP | `openfdd-mcp` stdio (optional, external) |
| Embedded chatbot | **Removed** — use external MCP/REST |

## External orchestration

| Role | Tooling |
|------|---------|
| Runtime | Open-FDD Rust edge only |
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
