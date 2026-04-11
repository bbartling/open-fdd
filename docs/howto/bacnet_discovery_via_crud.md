---
title: BACnet discovery via CRUD (archived pattern)
parent: How-to guides
nav_order: 99
nav_exclude: true
---

# BACnet discovery via CRUD (archived pattern)

**This page is intentionally retired.** Open-F-DD **does not** host BACnet discovery or scrapers in the default architecture. **Per-building VOLTTRON** owns BACnet (and Modbus) on the **ZMQ** message bus; telemetry reaches Open-F-DD through **SQL** and **`external_id`** mapping.

- Read **[Site VOLTTRON and the data plane (ZMQ)](../concepts/site_volttron_data_plane)** and **[Edge field buses (VOLTTRON)](../bacnet/)**.
- Historical FastAPI + diy-bacnet flows live only in **`afdd_stack/legacy/README.md`** and **git history** (`docs/howto/bacnet_discovery_via_crud.md` prior revisions).
