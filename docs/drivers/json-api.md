---
title: JSON API driver
parent: Driver framework
nav_order: 3
---

# JSON API driver

Poll **HTTP or HTTPS** REST endpoints on the OT LAN (or a bench API such as [JSONPlaceholder](https://jsonplaceholder.typicode.com/)) and store extracted JSON values in the feather historian (`source=json_api`).

Use this driver for gateways, micro-PLCs, IoT hubs, and vendor APIs that expose JSON over HTTP instead of BACnet or Modbus.

## Supported features

| Feature | Support |
|---------|---------|
| Methods | `GET`, `POST` |
| Transport | `http://` and `https://` |
| TLS certificate verify | On by default; disable for self-signed OT gateways |
| Authentication | None, **Bearer token**, **HTTP Basic** |
| Custom headers | Optional `headers` map (merged with auth headers) |
| Value extraction | Dot-path into JSON body (`title`, `data.temp`, `items.0.value`) |
| Polling | 1 / 5 / 10 / 15 minutes (same worker pattern as BACnet/Modbus) |
| Historian | `workspace/json_api/polls/samples.csv` → `feather_store/json_api/` |

## Commissioning (UI)

1. Sign in → **JSON API** tab (below Modbus).
2. Enter URL, method, JSON path, and label (historian column name).
3. Set **Auth** if the device requires it:
   - **Bearer token** — common for API keys and JWT gateways.
   - **HTTP Basic** — username/password for legacy OT web servers.
4. **TLS verify** — leave checked for public HTTPS; uncheck for `https://192.168.x.x` with a self-signed certificate.
5. Click **Request & store to historian** — endpoint is saved to `endpoints.csv` and a feather shard is written.
6. In the tree, right-click or bulk-select → **Poll 1 min** (etc.).

### Bench preset

Use the **Todo title** preset against JSONPlaceholder to verify outbound HTTPS without field hardware.

## Authentication examples

### Bearer token (API key)

```json
{
  "url": "https://192.168.10.50/api/v1/status",
  "method": "GET",
  "json_path": "sensors.zone_temp",
  "label": "zone-temp",
  "auth_type": "bearer",
  "bearer_token": "your-api-key-here",
  "verify_tls": false
}
```

### HTTP Basic

```json
{
  "url": "http://192.168.10.50/data.json",
  "method": "GET",
  "json_path": "value",
  "label": "sensor-value",
  "auth_type": "basic",
  "basic_user": "operator",
  "basic_password": "changeme"
}
```

### POST with JSON body

```json
{
  "url": "https://gateway.local/api/read",
  "method": "POST",
  "json_path": "result.pv",
  "label": "pv",
  "body": { "point": "AHU-1_SAT", "command": "read" },
  "auth_type": "bearer",
  "bearer_token": "…"
}
```

Credentials are stored in `workspace/json_api/commissioning/endpoints.csv` on the edge host (local OT commissioning model). Restrict filesystem access on production boxes.

## REST API

| Method | Path | Role | Description |
|--------|------|------|-------------|
| GET | `/api/json-api/driver/tree` | operator+ | Commissioning tree grouped by host |
| GET | `/api/json-api/poll/status` | operator+ | Poll worker status |
| POST | `/api/json-api/poll/once` | integrator+ | Run one poll cycle |
| POST | `/api/json-api/request` | operator+ | One-shot HTTP request (no store) |
| POST | `/api/json-api/read_and_store` | operator+ | Request + CSV + feather ingest |
| POST | `/api/json-api/refresh` | operator+ | Re-fetch one endpoint |
| PATCH | `/api/json-api/endpoint/poll` | integrator+ | Enable/disable poll interval |
| DELETE | `/api/json-api/endpoint/{point_id}` | integrator+ | Remove endpoint |

Full route list: [API routes](../appendix/bridge_api).

## Typical OT URLs

| Device type | Example URL | Notes |
|-------------|-------------|-------|
| Gateway status | `http://192.168.1.50/api/status` | Often plain HTTP on LAN |
| HTTPS BMS API | `https://10.0.0.12/rest/points/zone1` | May need `verify_tls: false` |
| Local mock | `https://jsonplaceholder.typicode.com/todos/1` | Bench / CI only |

## Limitations

- Response body must be **JSON** (not XML or plain text).
- Extracted values are stored as **strings** in feather; numeric FDD rules should use BACnet or Modbus for float trends.
- Outbound requests originate from the **bridge** container/host — ensure routing and firewall rules allow the edge box to reach the OT subnet.

## Smoke test

```bash
python3 scripts/smoke_multi_driver_stack.py
```

Validates JSON API ingest alongside BACnet and Modbus, feather isolation, BRICK scope, and FDD batch.
