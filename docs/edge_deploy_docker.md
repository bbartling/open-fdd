---
title: Edge Docker deploy
nav_order: 10
---

# Edge Docker deploy

Open-FDD edge hosts run **three** GHCR containers (`bridge`, `commission`, `mcp-rag`) with `workspace/` bind-mounted for site state.

| Task | Doc |
|------|-----|
| First deploy | [Quick Start — Run with Docker images](quick-start/docker) |
| Backup + image upgrade | [Quick Start — Updating the stack](quick-start/updating) |
| Container architecture | [Architecture — Containers](architecture/containers) |
| BACnet polling | [BACnet — Polling](bacnet/polling) |

Typical host layout:

```text
~/open-fdd/
  docker-compose.yml    # from docker/compose.edge.yml
  workspace/            # historian, BACnet, auth — backup before upgrades
```

Compose template: `docker/compose.edge.yml` in the repo.
