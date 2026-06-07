---
title: Containers
parent: Architecture
nav_order: 3
---

# Containers

Open-FDD publishes **four** GHCR images. A typical production site runs **three** of them.

## GHCR images

| Image | Role |
|-------|------|
| `ghcr.io/bbartling/openfdd-bridge` | Operator API, React dashboard, feather **ingest** worker |
| `ghcr.io/bbartling/openfdd-commission` | BACnet discover / read / write agent; **default poll loop** |
| `ghcr.io/bbartling/openfdd-mcp-rag` | Optional doc-search sidecar |
| `ghcr.io/bbartling/openfdd-bacnet-poll` | **Optional** dedicated BACnet RPM poll driver (host network) |

Tags: [GitHub Packages](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) (e.g. `2026.06.07-edge`).

## Standard 3-container stack (default)

```
┌─────────────────────────────────────────────────────────────┐
│  bridge                                                     │
│  • REST API + dashboard (:8765, often behind Caddy :80)     │
│  • bacnet_poll_worker thread → watches samples.csv → feather  │
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

**BACnet field reads** happen in the **commission** container (`bacnet_poll_loop` inside `commission_agent`).  
The bridge’s `bacnet_poll_worker` is **not** a BACnet driver — it only **ingests** new rows from `samples.csv` into the feather historian.

This is why `docker compose ps` shows three services and BACnet polling still works.

## Optional 4th container (`bacnet-poll`)

Enable only when you **disable** the commission poll loop and want a standalone RPM driver:

```bash
docker compose --profile bacnet-poll up -d
```

| | Commission poll loop (default) | `bacnet-poll` container |
|--|-------------------------------|-------------------------|
| BACnet bind | commission (host network) | bacnet-poll (host network) |
| Output | `workspace/bacnet/polls/samples.csv` | same |
| When to use | **Normal edge sites** | Legacy / special split deployments |

{: .warning }
> **Never run both** commission poll loop and `bacnet-poll` on the same host — they would double-bind BACnet port 47808.

## Persistent data

State lives on the **host** under `workspace/` (bind mount). Containers are disposable.

| Path | Contents |
|------|----------|
| `workspace/data/feather_store/` | Historian |
| `workspace/data/*.json` | Model, rules, FDD results |
| `workspace/bacnet/commissioning/` | `commission.env`, `points.csv` |
| `workspace/bacnet/polls/samples.csv` | Poll output (long format) |
| `workspace/auth.env.local` | Login secrets |
| `workspace/api/static/app/` | Dashboard bundle (if updated separately) |

## Host services (optional)

- **Caddy** on `:80` → reverse proxy to bridge `:8765` (recommended LAN entry)
- **Ollama** on host or separate container (optional AI)

See [Run with Docker images](../quick-start/docker) for IT deployment steps.
