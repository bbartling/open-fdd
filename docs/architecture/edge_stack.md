---
title: Edge stack layout
parent: Getting Started
nav_order: 4
---

# Edge stack layout

Three layers on a field host (today: **Ubuntu + Docker CE**; future: thin image under `os/`).

| Layer | Repo path | Role |
|-------|-----------|------|
| **Host** | OS + Caddy + timers | LAN :80, optional GPU Ollama, `docker compose exec` for FDD loop |
| **Supervisor** | `supervisor/` | Manifest, compose contracts, health — `./scripts/openfdd_stack.sh` |
| **Apps** | `docker/` images | bridge, commission, poll, mcp-rag |
| **State** | `workspace/` | Feather, rules, BRICK model, BACnet config (bind-mounted) |
| **Deploy** | `infra/ansible/` | GHCR `compose pull` + workspace sync — `deploy.sh docker` (tar optional) |

```text
  [Caddy :80]
       ↓
  openfdd-bridge (:8765) ← workspace/data, static UI
       ↓ HTTP
  openfdd-commission (:8767) ← BACNET_BIND on OT NIC
  openfdd-bacnet-poll (host net) → samples → feather
  openfdd-mcp-rag (:8090) ← optional doc search
```

**ADR:** [Core addon serves SPA](adr-001-core-addon-spa) — UI ships inside `openfdd-bridge`.

Future `os/` Buildroot image: `os/README.md` (not required for current Acme/bensserver deploys).
