---
title: Operator override scans
parent: BACnet
nav_order: 4
---

# Operator override scans (P8)

The commission agent rotates **one BACnet device per hour** (default) through a supervisory priority-array scan. Results are persisted for operator review and portfolio rollup — not for automatic writes.

## Schedule

| Setting | Default | Meaning |
|---------|---------|---------|
| `OFDD_OVERRIDE_SCAN_INTERVAL_S` | `3600` | Seconds between single-device scans |
| `OFDD_OPERATOR_OVERRIDE_PRIORITY` | `8` | BACnet priority counted as “operator override” |
| Device list | `points_discovered.csv` | Unique `device_instance` rows |
| Rotation | `registry.json` cursor | Full plant rotation ≈ `device_count × interval` |

Example: **33 devices × 1 h** ≈ **33 h** for a full pass. Dashboard shows **next device** and **last scan** time.

## What each scan does

1. `point_discovery` on the target device (commandable objects).
2. `read_property` on each object’s **priority-array** (not RPM — RPM loses priority slots).
3. Merge into `workspace/bacnet/overrides/registry.json` and append `overrides_export.csv`.
4. Advance cursor to the next device.

Fault code **operator_override** (P8) surfaces active overrides on the BACnet tree and building status.

## BACnet I/O priority

Override scans run at **BACKGROUND** priority on the single shared BACnet stack (UDP 47808). Operator reads/writes use **INTERACTIVE** and preempt background work. Scheduled RPM polling also uses BACKGROUND and shares the same asyncio lock — polls and override scans take turns; neither starves the other indefinitely.

Override scans allow up to **15 minutes** per device (`_run_bacnet_override_scan` timeout). Bridge `POST /api/bacnet/overrides/scan-once` proxies with a matching 900 s timeout.

## Manual trigger

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://EDGE:8765/api/bacnet/overrides/scan-once
```

Dashboard: BACnet page → **Scan next device now**.

## Health checks

```bash
curl -H "Authorization: Bearer $TOKEN" http://EDGE:8765/api/bacnet/overrides/status
```

Expect `device_count` > 0, `last_scan_at` within the last few hours on a healthy edge, and `export_row_count` growing over time.

## Data paths

| Path | Content |
|------|---------|
| `workspace/bacnet/overrides/registry.json` | Per-device last scan + override points |
| `workspace/bacnet/overrides/overrides_export.csv` | Flat export for spreadsheets |

Preserved across Docker upgrades when `workspace/` is on the edge volume — see [Backup & restore]({{ "/ops/backup-restore/" | relative_url }}).
