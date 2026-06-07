---
title: Containers
parent: Architecture
nav_order: 3
---

# Containers

Open-FDD v3 edge sites run **three** GHCR containers plus optional **host** services (Caddy, Ollama). There is no separate BACnet poll container — polling is part of **commission**.

## GHCR images

| Image | Compose service | Role |
|-------|-----------------|------|
| `ghcr.io/bbartling/openfdd-bridge` | `bridge` | Operator API, React dashboard, feather **ingest** |
| `ghcr.io/bbartling/openfdd-commission` | `commission` | BACnet discover / read / write + **poll loop** |
| `ghcr.io/bbartling/openfdd-mcp-rag` | `mcp-rag` | Doc-search sidecar for agent tools |

Tags: [GitHub Packages](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) (e.g. `2026.06.07-edge`).

Template: `docker/compose.edge.yml` → copy to `~/open-fdd/docker-compose.yml`.

## Stack diagram

```
                    ┌── Caddy :80 (host, optional) ──┐
                    ▼                                │
┌─────────────────────────────────────────────────────────────┐
│  bridge (bridge network)                                    │
│  • :8765 API + dashboard (127.0.0.1 on host by default)     │
│  • ingest worker: samples.csv → feather_store               │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP → commission :8767, mcp-rag :8090
┌───────────────────────────▼─────────────────────────────────┐
│  commission (network_mode: host)                            │
│  • BACnet :47808 on OT NIC                                  │
│  • poll loop → workspace/bacnet/polls/samples.csv           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  mcp-rag (bridge network, internal :8090)                   │
└─────────────────────────────────────────────────────────────┘
```

## Responsibilities

| Concern | Container |
|---------|-----------|
| BACnet Who-Is / read / write | **commission** |
| BACnet scheduled RPM reads | **commission** (`bacnet_poll_loop`) |
| CSV → feather historian | **bridge** (`bacnet_poll_worker` thread) |
| Operator login, Rule Lab, faults UI | **bridge** |
| Agent doc search | **mcp-rag** |

The bridge thread named `bacnet_poll_worker` is **ingest only** — it does not bind BACnet.

## Network and ports (typical edge)

| Endpoint | Reachable from | Notes |
|----------|----------------|-------|
| Caddy `:80` | Building LAN | Reverse proxy to bridge |
| Bridge `:8765` | Loopback (default) | Bind `127.0.0.1` in compose |
| Commission `:8767` | Bridge / loopback | HTTP API for BACnet ops |
| Commission `:47808` | OT BACnet LAN | UDP; requires `network_mode: host` |
| MCP `:8090` | Bridge container network | Not exposed to LAN by default |

## Long-lived deployment

All compose services set `restart: unless-stopped`. After host reboot:

```bash
sudo systemctl enable docker
cd ~/open-fdd && docker compose ps
```

If containers are down: `docker compose up -d` (idempotent).

See [Run with Docker images](../quick-start/docker).

## Persistent data

State lives on the **host** under `workspace/` (bind mount). Containers are replaceable; **backup `workspace/`** before image upgrades.

| Path | Contents |
|------|----------|
| `workspace/data/feather_store/` | Historian |
| `workspace/data/*.json` | Model, rules, FDD results |
| `workspace/bacnet/commissioning/` | `commission.env`, `points.csv` |
| `workspace/bacnet/polls/samples.csv` | Poll output |
| `workspace/auth.env.local` | Login secrets |
| `workspace/api/static/app/` | Dashboard bundle (if updated separately) |

## Optional host services

| Service | Role |
|---------|------|
| **Caddy** | TLS or plain HTTP `:80` → `127.0.0.1:8765` |
| **Ollama** | Optional LLM on `:11434` (not in the three-image stack) |
| **FDD loop timer** | Optional `openfdd-fdd-loop.timer` on host (`docker exec` batch) |
