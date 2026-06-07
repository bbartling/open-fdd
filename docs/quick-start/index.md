---
title: Quick Start
nav_order: 2
has_children: true
---

# Quick Start

Run Open-FDD on a Linux edge host using **published GHCR Docker images**. No git clone on the host.

| Step | Page |
|------|------|
| 1 | [Run with Docker images](docker) — pull `bridge`, `commission`, `mcp-rag` |
| 2 | [First login and health check](health-check) |
| 3 | [Updating the stack](updating) — backup + `docker compose pull` |

**Scripts on the edge host:**

```bash
./scripts/openfdd_site_backup.sh
export NEW_TAG=2026.06.07-edge && ./scripts/openfdd_site_update.sh
```

**Prerequisites:** Linux, Docker Compose, BACnet LAN access if polling OT equipment.

{: .warning }
> **BACnet writes are disabled by default.** See [Write safety](../bacnet/write-safety).

**Architecture:** Four GHCR images exist; standard sites run **three** containers because BACnet polling lives in **commission**. Details: [Containers](../architecture/containers).
