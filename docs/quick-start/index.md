---
title: Quick Start
nav_order: 2
has_children: true
---

# Quick Start

Run Open-FDD on a Linux edge host using **three GHCR Docker images**. No git clone on the host.

| Step | Page |
|------|------|
| 1 | [Run with Docker images](docker) — bootstrap script + `docker compose up` |
| 2 | [First login and health check](health-check) |
| 3 | [Updating the stack](updating) — backup + pull |

**One-liner bootstrap** (edge host):

```bash
curl -fsSL -o /tmp/openfdd_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh
bash /tmp/openfdd_edge_bootstrap.sh --start
```

**Prerequisites:** Linux, Docker enabled on boot, BACnet LAN if polling OT equipment.

{: .warning }
> **BACnet writes are disabled by default.** See [Write safety](../bacnet/write-safety).

**Stack:** `bridge` + `commission` (BACnet + poll) + `mcp-rag`. Details: [Containers](../architecture/containers).
