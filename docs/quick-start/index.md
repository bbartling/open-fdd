---
title: Quick Start
nav_order: 2
has_children: true
---

# Quick Start

Run Open-FDD on a Linux edge host using **three GHCR Docker images**. No git clone on the host.

| Step | Page |
|------|------|
| 1 | [Run with Docker images](docker) — pull, `up -d`, survive reboots |
| 2 | [First login and health check](health-check) |
| 3 | [Updating the stack](updating) — backup + `docker compose pull` |

**Helper scripts** (copy from repo to the host, or keep a minimal checkout):

```bash
./scripts/openfdd_site_backup.sh
export NEW_TAG=2026.06.07-edge && ./scripts/openfdd_site_update.sh
```

**Prerequisites:** Linux, Docker enabled on boot, BACnet LAN if polling OT equipment.

{: .warning }
> **BACnet writes are disabled by default.** See [Write safety](../bacnet/write-safety).

**Stack:** `bridge` + `commission` (BACnet + poll) + `mcp-rag`. Details: [Containers](../architecture/containers).
