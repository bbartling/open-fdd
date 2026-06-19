---
title: Quick Start
nav_order: 2
has_children: true
---

# Quick Start

Run Open-FDD on a Linux edge host using **three GHCR Docker images**. No git clone on the host.

| Step | Page |
|------|------|
| 1 | [Run with Docker images]({{ "/quick-start/docker/" | relative_url }}) — bootstrap script + `docker compose up` |
| 2 | [First login and health check]({{ "/quick-start/health-check/" | relative_url }}) |
| 3 | [Edge site lifecycle]({{ "/quick-start/site-lifecycle/" | relative_url }}) — backup, update, restore |
| 4 | [Updating the stack]({{ "/quick-start/updating/" | relative_url }}) — operator checklist |

**One-liner bootstrap** (edge host):

```bash
curl -fsSL -o /tmp/openfdd_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh
bash /tmp/openfdd_edge_bootstrap.sh --start
```

**Prerequisites:** Linux, Docker enabled on boot, BACnet LAN if polling OT equipment.

{: .warning }
> **BACnet writes are disabled by default.** See [Write safety]({{ "/bacnet/write-safety/" | relative_url }}).

**Stack:** `bridge` + `commission` (BACnet + poll) + `mcp-rag`. Details: [Containers]({{ "/architecture/containers/" | relative_url }}).
