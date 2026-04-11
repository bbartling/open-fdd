---
title: RDF, Brick, and optional BACnet-shaped metadata
nav_order: 2
parent: Concepts
---

# RDF, Brick, and optional BACnet-shaped metadata

Open-F-DD models the building as a **Brick-oriented knowledge graph** in `config/data_model.ttl` when you run **FastAPI**. **CRUD**, **SPARQL**, and **data-model import/export** maintain sites, equipment, and points.

**BACnet on the wire** is **not** owned by Open-F-DD in the default architecture: **site VOLTTRON** performs discovery and reads/writes devices; **historians** persist time series to **Postgres**. Any **BACnet-shaped RDF** in the graph is either **legacy** (from older deployments), **imported**, or produced only if **you** explicitly run **legacy** `/bacnet/point_discovery_to_graph` against a **separate** lab gateway — not something this documentation recommends for new ingest.

**Preferred path:** align **`external_id`** and SQL rows with VOLTTRON topics ([Site VOLTTRON and the data plane (ZMQ)](../concepts/site_volttron_data_plane)), use **SPARQL** for validation, and keep Brick metadata in sync via CRUD or import.

See also **[Edge field buses (VOLTTRON)](bacnet/)** (docs index entry under **BACnet** path for historical URLs).
