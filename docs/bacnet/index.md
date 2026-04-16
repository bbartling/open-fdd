---
title: Field data and BACnet-shaped metadata
nav_order: 6
has_children: false
---

# Field data and BACnet-shaped metadata

The **`open-fdd`** engine consumes **pandas** `DataFrame`s. It does **not** speak BACnet, Modbus, or other field protocols.

If your integration maps BACnet object names (or similar) into column names or Brick-style identifiers, use **column_map** manifests or a custom resolver—see [Column map resolvers](../column_map_resolvers) and [RDF, Brick, and optional BACnet-shaped metadata](../bacnet-rdf-and-brick).

For BACnet **discovery or control**, use your building’s **gateway, BMS, or integration stack**, then pass normalized data into the engine.
