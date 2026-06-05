---
title: Polling
parent: BACnet
nav_order: 3
---

# Polling

The **bacnet-poll** container runs scheduled reads defined in `device_poll_profiles.csv` and enabled points in `points.csv`.

| Setting | Location |
|---------|----------|
| Poll profiles | `workspace/bacnet/polls/` |
| Enabled points | `workspace/data/points.csv` |
| Output | `workspace/data/feather_store/` |

## Enable on edge

Host var `enable_bacnet_poll_driver: true` in Ansible (or compose profile). Driver requires host networking on Linux.

## Health

- Dashboard poll status shows last cycle time.
- Stale points trigger data-quality fault patterns — see [Sensor quality faults](../fault-codes/sensor-quality).
