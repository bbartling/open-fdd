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
| [**Local stack (Compose)**](local-stack.html) | **Recipe 2** OT edge / LAN — central + web + protocol |
| [**Railway hub**](railway-hub.html) | **Recipe 1** cloud hub — mqtt + central + web (amd64) |
| [Raspberry Pi edge](raspberry-pi-edge.html) | Recipe 2 on arm64 — Soft-OPEN until multi-arch tip boots |
| [Site lifecycle](site-lifecycle.html) | Backup, update, restore |

Two named recipes: **Recipe 1** = cloud hub (`mqtt` + `central` + `web`, amd64). **Recipe 2** = OT edge (`central` + `web` + protocol; broker **not** required; optional MQTTS publish to a hub). Matrix: [Build recipes](../operations/build-recipes.md).

Public **Operations** docs hub was removed — bootstrap lives here. In-repo ops notes remain under `docs/operations/` for agents.
