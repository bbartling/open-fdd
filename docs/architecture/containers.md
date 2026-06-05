---
title: Containers
parent: Architecture
nav_order: 3
---

# Containers

| Container | Network | Persistent mounts |
|-----------|---------|-------------------|
| `openfdd-bridge` | bridge | `workspace/` (data, api static, auth env) |
| `openfdd-commission` | host or bridge | `workspace/bacnet/` |
| `openfdd-bacnet-poll` | **host** | `workspace/data/`, poll profiles |
| `openfdd-mcp-rag` | bridge | read-only docs index |

**Host services (typical edge):** Caddy, optional Ollama, `openfdd-fdd-loop.timer` (docker exec batch).

State lives on the **host filesystem** under `workspace/` — containers are replaceable. Prefer GHCR image upgrades over re-provisioning the VM when possible.
