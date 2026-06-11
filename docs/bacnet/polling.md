---
title: Polling
parent: BACnet
nav_order: 3
---

# Polling

**BACnet field reads run in the `openfdd-commission` container.** The Operator Bridge does not bind UDP 47808.

{: .note }
> **Retired:** `openfdd-bacnet-poll` image and `openfdd-bacnet-poll` systemd unit. Poll loop lives in **commission** only — do not run both.

BACnet polling has two stages:

1. **Field reads** — commission poll loop → `workspace/bacnet/polls/samples.csv`
2. **Historian ingest** — bridge background worker → `workspace/data/feather_store/`

## Commission poll loop (default)

The **commission** container runs the poll loop at startup. It reads enabled rows from `points.csv` and appends BACnet RPM results to `samples.csv`.

| Setting | Location |
|---------|----------|
| BACnet bind | `workspace/bacnet/commissioning/commission.env` |
| Enabled points | `workspace/bacnet/commissioning/points.csv` |
| Poll output | `workspace/bacnet/polls/samples.csv` |
| Historian | `workspace/data/feather_store/` |

Check activity:

```bash
tail -1 workspace/bacnet/polls/samples.csv
docker compose logs --since 5m commission | grep -i poll
```

## Bridge ingest worker

Inside **bridge**, a background thread watches `samples.csv` and ingests new rows into feather. Disable only for debugging: `OFDD_DISABLE_POLL_WORKER=1`.

## Health

Dashboard stack health (`GET /health/stack`) reports `bacnet_poll` status from the commission agent — not a separate container.

Stale points trigger data-quality fault patterns — see [Sensor quality faults]({% link fault-codes/sensor-quality.md %}).

## Poll strategy (edge)

Open-FDD intentionally keeps BACnet field traffic **minimal**:

- **One enabled row per object** in `points.csv` — poll only what the model/FDD needs.
- **Uniform cycle** — every enabled point is RPM-polled each cycle; the loop sleeps `max(15, min(poll_interval_s))` (typically **60 s** on Acme).
- Per-point `poll_interval_s` in the UI is the **commissioned target**; throughput analytics compare configured vs observed samples.
- **Unit conversion** (e.g. Trane °C → °F) uses `device_poll_profiles.csv` at ingest — not a poll-rate file.

Acme ships ~**340 points / 60 s** ≈ one full plant read per minute. Disable unneeded objects in BACnet commissioning rather than raising global poll rates.

## Async driver and single-stack I/O

| Layer | Behavior |
|-------|----------|
| Dedicated `bacnet-io` thread | One asyncio loop + serial lock for all field I/O |
| RPM batching | Present-value reads chunked (25 objects) to cut APDUs |
| Poll loop | Sequential per-device RPM when `interruptible=True` so operator UI can preempt |
| Operator UI | **INTERACTIVE** priority — cancels in-flight background work |
| Override scans | **BACKGROUND**, 15 min timeout — see [Operator override scans]({% link bacnet/override-scans.md %}) |
| Bridge ingest | Async notify after each poll cycle → feather historian |

Do **not** run a second BACnet bind on 47808 (no parallel `openfdd-bacnet-poll` container). See [Containers]({% link architecture/containers.md %}).

## Operator override scans

Hourly P8 supervisory scans rotate one device at a time. Documented in [Operator override scans]({% link bacnet/override-scans.md %}).
