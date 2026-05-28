---
title: BACnet toolshed
nav_order: 6
has_children: false
---

# BACnet toolshed

The **`open_fdd`** engine runs on **pandas** only. BACnet **discovery**, **commissioning CSVs**, and **polling** live in **`bacnet_toolshed/`** at the repo root (BACpypes3).

## Edge workflow

1. **Discover** points → `workspace/bacnet/commissioning/points_discovered.csv`
2. **Enable** rows + optional **`brick_class`** for `column_map` → `points.csv`
3. **Poll** present-values → `workspace/bacnet/polls/samples.csv`
4. **Bridge + dashboard** (generated under `workspace/`) ingest CSV/Feather and expose BACnet NIC settings in the UI

See **[bacnet_toolshed/README.md](https://github.com/bbartling/open-fdd/blob/dev/bacnet_toolshed/README.md)** for CLI examples, OT NIC args (`--name`, `--instance`, `--address`), and systemd unit templates.

## Engine integration

Map BACnet commissioning columns to DataFrame columns via **[Column map resolvers](../column_map_resolvers)**. **`brick_class`** in the commissioning CSV can align with optional **`brick:`** fields in rule YAML.

Skill: **`driver-bacnet-ingest`** (agent builds bridge routes and `/bacnet-tools` dashboard page).
