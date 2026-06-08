---
title: Home
nav_order: 1
description: "Open-FDD — open-source HVAC fault detection and building data platform."
---

# Open-FDD

Open-FDD is an open-source **building edge platform** for BACnet integration, feather historian storage, Arrow-native fault detection, and operator dashboards — designed for **trusted LAN / OT edge** deployment behind Caddy, not direct public internet exposure.

## Who it is for

| Role | What you get |
|------|----------------|
| **IT / controls engineer** | Pull three GHCR images, log in, poll BACnet, view faults |
| **Commissioning integrator** | Discover points, bind BRICK model, pin FDD rules in Rule Lab |
| **Developer / maintainer** | Extend the Operator Bridge, publish images, run CI and LAN security scans |

## Start here

| Path | Go to |
|------|-------|
| **Try it** | [Quick Start — Run with Docker](quick-start/docker) |
| **Operate it** | [Updating the stack](quick-start/updating) · [Operations](ops/) |
| **Develop it** | [Developer Guide](developer/) · [Architecture](architecture/) |

## v3 edge stack

Three primary containers on a Linux edge host:

| Container | Role |
|-----------|------|
| **openfdd-bridge** | Operator Bridge — API, dashboard, feather **ingest** |
| **openfdd-commission** | BACnet discover/read/write + **poll loop** |
| **openfdd-mcp-rag** | Doc-search sidecar for agent tools |

Host **Caddy** on `:80` or `:443` is the normal LAN front door. BACnet UDP `:47808` is bound by **commission** only — the bridge ingests `samples.csv` into the feather historian.

Details: [Containers](architecture/containers) · [Deployment modes](architecture/deployment-modes)

{: .warning }
> **LAN / OT edge only.** Do not expose the Operator Bridge to the public internet without TLS, strong auth, and site review. BACnet writes are disabled by default — see [BACnet write guard](security/bacnet-writes).

## Distribution

| Channel | Use when |
|---------|----------|
| **GHCR** `ghcr.io/bbartling/openfdd-*` | Production or trial edge deploy |
| **This repository** | Custom builds, commissioning, Rule Lab development |
| **PyPI** [`open-fdd`](https://pypi.org/project/open-fdd/) | Arrow runtime lint/test without full UI |

## License

MIT — see repository `LICENSE`.
