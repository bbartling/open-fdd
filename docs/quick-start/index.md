---
title: Quick Start
nav_order: 2
has_children: true
---

# Quick Start

Run Open-FDD on a Linux edge host or VM using **published Docker images**. No local image build required.

| Step | Page |
|------|------|
| 1 | [Run with Docker images](docker) |
| 2 | [First login and health check](health-check) |
| 3 | [Updating the stack](updating) — Ansible or SSH paths |
| — | [Live site update (SSH)](../ops/live_site_update) — minimal VM folder, no `git pull` |

**Prerequisites:** Linux host with Docker and Docker Compose, network access to BACnet devices if polling OT equipment, and a safe lab or maintenance window for first BACnet discovery.

{: .warning }
> **BACnet writes are disabled by default.** Do not enable write paths on live equipment without an allowlist and operator authorization. See [Write safety](../bacnet/write-safety).
