---
title: Edge Docker deploy
nav_order: 10
---

# Edge Docker deploy

Open-FDD edge hosts run three GHCR images (bridge, commission, mcp-rag) with `workspace/` bind-mounted for site state.

| Phase | Doc |
|-------|-----|
| **First deploy** (Ansible or bootstrap) | [Quick Start — Run with Docker images](quick-start/docker) |
| **Live site update** (SSH, minimal folder, no `git pull`) | [Operations — Live site update](ops/live_site_update) |
| **Image-only upgrade** (control machine + inventory) | [Quick Start — Updating the stack](quick-start/updating) |
| **Full upgrade** (UI static bundle + images) | `scripts/upgrade_edge_full.sh` — see [Live site update §3](ops/live_site_update#3-update-the-react-ui-bundle-required-for-dashboard-changes) |

The live VM layout is only `docker/`, `docker-compose.yml`, and `workspace/` — not a full git checkout. Use the [live site update](ops/live_site_update) runbook for tag bumps on that layout.
