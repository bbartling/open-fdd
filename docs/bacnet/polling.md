---
title: Polling
parent: BACnet
nav_order: 3
---

# Polling

**BACnet field reads run in the `commission` container** (or legacy `openfdd-bacnet-commission` systemd unit). The bridge does not bind UDP 47808.

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

Stale points trigger data-quality fault patterns — see [Sensor quality faults](../fault-codes/sensor-quality).
