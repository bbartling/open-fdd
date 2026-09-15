---
title: Quick Start
layout: default
nav_order: 2
has_children: true
permalink: /quick-start/
---

# Quick Start

Install Open-FDD from GHCR, bring up **local** or **Railway** hubs, verify health, and follow backup → update → validate.

| Guide | Audience |
|-------|----------|
| [Docker & GHCR](docker-ghcr.html) | Image channels and first pull |
| [**Local stack (Compose)**](local-stack.html) | LAN / VPN host — `openfdd_stack_up.sh` |
| [**Railway hub**](railway-hub.html) | Cloud central + web + mqtt; fieldbus on-prem |
| [Raspberry Pi edge](raspberry-pi-edge.html) | ARM64 / Pi fieldbus-only |
| [Site lifecycle](site-lifecycle.html) | Backup, update, restore |

Public **Operations** docs hub was removed — bootstrap lives here. In-repo ops notes remain under `docs/operations/` for agents.
