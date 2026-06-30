---
title: Modbus
parent: Drivers
nav_order: 2
---

# Modbus driver

Modbus/TCP is handled in the **bridge** service alongside JSON API sources.

## Key API routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/modbus/driver/tree` | Device/register tree |
| POST | `/api/modbus/scan` | Discover devices |
| POST | `/api/modbus/read` | Read registers |
| GET | `/api/modbus/poll/status` | Poll status |

## Dashboard

**Modbus** tab (`/modbus`) — same commissioning pattern as BACnet: tree, poll rates, historian storage.

Enable with `OPENFDD_MODBUS_ENABLED=1` (default in full-edge profile).
