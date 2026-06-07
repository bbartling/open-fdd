---
title: Containers
parent: Architecture
nav_order: 3
---

# Containers

Open-FDD publishes **three** GHCR images for production edge sites.

## GHCR images

| Image | Role |
|-------|------|
| `ghcr.io/bbartling/openfdd-bridge` | Operator API, React dashboard, feather **ingest** worker |
| `ghcr.io/bbartling/openfdd-commission` | BACnet discover / read / write + **poll loop** |
| `ghcr.io/bbartling/openfdd-mcp-rag` | Doc-search sidecar |

Tags: [GitHub Packages](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) (e.g. `2026.06.07-edge`).

## Stack diagram

```
┌─────────────────────────────────────────────────────────────┐
│  bridge                                                     │
│  • REST API + dashboard (:8765, often behind Caddy :80)     │
│  • ingest worker → watches samples.csv → feather_store      │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP
┌───────────────────────────▼─────────────────────────────────┐
│  commission (host network for BACnet :47808)                  │
│  • discover / read / write                                  │
│  • poll loop → workspace/bacnet/polls/samples.csv           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  mcp-rag — doc search (:8090, internal)                     │
└─────────────────────────────────────────────────────────────┘
```

**BACnet field reads** run in **commission** (`bacnet_poll_loop` in `commission_agent`).  
The bridge ingest worker does **not** talk to BACnet — it loads new CSV rows into feather.

All compose services use `restart: unless-stopped` for reboot survival when Docker is enabled on boot.

## Persistent data

State lives on the **host** under `workspace/` (bind mount). Containers are replaceable.

| Path | Contents |
|------|----------|
| `workspace/data/feather_store/` | Historian |
| `workspace/data/*.json` | Model, rules, FDD results |
| `workspace/bacnet/commissioning/` | `commission.env`, `points.csv` |
| `workspace/bacnet/polls/samples.csv` | Poll output |
| `workspace/auth.env.local` | Login secrets |
| `workspace/api/static/app/` | Dashboard bundle (if updated separately) |

## Host services (optional)

- **Caddy** on `:80` → bridge `:8765`
- **Ollama** on host (optional AI)

See [Run with Docker images](../quick-start/docker).
