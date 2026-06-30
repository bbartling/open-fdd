---
title: JSON API
parent: Drivers
nav_order: 4
---

# JSON API driver

Poll HTTP/HTTPS endpoints (GET or POST) with Bearer or Basic auth. Useful for cloud meters, REST gateways, and vendor APIs.

## Key API routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/json-api/sources` | Registered sources |
| POST | `/api/json-api/register` | Add endpoint |
| POST | `/api/json-api/poll-once` | Single poll |
| POST | `/api/json-api/read_and_store` | Poll + historian write |
| DELETE | `/api/json-api/endpoint/{point_id}` | Remove endpoint |

## Dashboard

**JSON API** tab (`/json-api`) — register endpoints, test requests, set poll intervals.

Enable with `OPENFDD_JSON_API_ENABLED=1`.
