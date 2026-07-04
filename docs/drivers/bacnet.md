---
title: BACnet
parent: Drivers
nav_order: 1
---

# BACnet driver

BACnet/IP runs in the **commission** container (`network_mode: host`). The bridge exposes commissioning UI and REST routes.

## Configuration

- `workspace/bacnet/commissioning/commission.env` — NIC, BBMD, device filters (**`OPENFDD_BACNET_SERVER_ENABLED=0`** on commission)
- `docker/compose.edge.rust.yml` — bridge vs commission server flags split (bridge **1**, commission **0**)
- `OPENFDD_BACNET_MODE` — `live` for field buses

{: .important }
**Compose split:** bridge runs the local diagnostic device (599999). Commission runs field Who-Is — never enable the local BACnet server on the commission container.

## Key API routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/bacnet/whois` | Discover devices |
| GET | `/api/bacnet/driver/tree` | Driver tree |
| POST | `/api/bacnet/read` | Read present value |
| GET | `/api/bacnet/poll/status` | Poll loop status |
| POST | `/api/bacnet/write-dry-run` | Simulate write |
| POST | `/api/bacnet/write` | **Live write — requires explicit approval** |

## Overrides

Scan and export priority-array overrides:

- `GET /api/bacnet/overrides/summary`
- `POST /api/bacnet/overrides/scan-once`

## Dashboard

**BACnet** tab (`/bacnet`) — scan, add devices, set poll rates, browse points.

{: .warning }
BACnet writes affect live equipment. Use dry-run first. Agents must not write without human approval.
