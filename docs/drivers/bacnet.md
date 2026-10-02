---
title: BACnet
parent: Drivers
nav_order: 1
---

# BACnet driver

BACnet/IP runs in the **fieldbus** container (`network_mode: host`), which polls
devices and publishes readings to central over MQTTS. Central exposes the
commissioning UI and REST routes; it never touches the BACnet wire itself.

## Configuration

- `config/fieldbus/` — device filters, NIC/BBMD, poll config for the fieldbus container
- Recipe: `standalone` runs fieldbus alongside central; `edge` runs fieldbus only and attaches to a remote central (see [Build recipes](../operations/build-recipes.md))
- `OPENFDD_BACNET_MODE` — `live` for field buses

{: .important }
The fieldbus container owns UDP 47808 and the local diagnostic device (599999).
Do not run a second BACnet server on the same host.

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

### Durable priority history

The connector capability and inventory surfaces expose a separate read-only
history action when the fieldbus has a trusted tenant/building/edge scope.
`POST /api/connector/priority-history` returns bounded, versioned snapshots
containing exactly P1–P16 for a selected configured object. The central route
`POST /api/connectors/{edge_id}/priority-history` forwards that same scoped
history only after authenticated tenant, building, and edge checks.

The scheduler is disabled unless `OPENFDD_PRIORITY_SCAN_ENABLED=1`. When
enabled it visits one configured device after each interval (default 3600
seconds, minimum 300), persists a stable device cursor and bounded records on
the edge, and advances the cursor after a complete device visit. It has no
catch-up burst and does not discover devices, write values, release priorities,
or remediate equipment. A read failure remains a typed error snapshot so the
history cannot silently turn a failed read into NULL data.

The cloud-only `central` and Railway recipes intentionally have no fieldbus
scanner or BACnet socket. MQTT history synchronization is not part of this
contract; use a separately versioned transport contract if that is added later.

## Dashboard

**BACnet** tab (`/bacnet`) — scan, add devices, set poll rates, browse points.

{: .warning }
BACnet writes affect live equipment. Use dry-run first. Agents must not write without human approval.
