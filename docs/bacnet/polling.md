---
title: Polling
parent: BACnet
nav_order: 3
---

# Polling

BACnet polling has two stages:

1. **Field reads** — RPM cycles write `workspace/bacnet/polls/samples.csv`
2. **Historian ingest** — bridge background worker loads new CSV rows into `workspace/data/feather_store/`

## Default: commission poll loop

On a standard Docker edge site, the **commission** container runs the poll loop at startup (`start_poll_loop` in `commission_agent`). It reads enabled rows from `points.csv` and appends to `samples.csv`.

No separate `bacnet-poll` container is required.

| Setting | Location |
|---------|----------|
| BACnet bind | `workspace/bacnet/commissioning/commission.env` |
| Enabled points | `workspace/bacnet/commissioning/points.csv` |
| Poll output | `workspace/bacnet/polls/samples.csv` |
| Historian | `workspace/data/feather_store/` |

Check poll activity:

```bash
tail -1 workspace/bacnet/polls/samples.csv
docker compose logs --since 5m commission | grep -i poll
curl -sf http://127.0.0.1:8765/health/stack   # needs integrator token
```

## Optional: dedicated `bacnet-poll` container

Image: `ghcr.io/bbartling/openfdd-bacnet-poll` (host network).

Use only when the commission poll loop is **off** and you want a standalone `poll_driver.py` process:

```bash
docker compose --profile bacnet-poll up -d bacnet-poll
```

Requires Linux host networking for OT BACnet bind. See [Containers](../architecture/containers) — do not run alongside commission polling.

## Bridge ingest worker

Inside the **bridge** container, `bacnet_poll_worker` watches `samples.csv` mtime and ingests new data into feather. Disable with `OFDD_DISABLE_POLL_WORKER=1` (unusual).

## Health

- Dashboard stack health shows `bacnet_poll` status (commission loop + ingest).
- Stale points trigger data-quality fault patterns — see [Sensor quality faults](../fault-codes/sensor-quality).
