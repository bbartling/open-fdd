---
title: API routes
parent: Appendix
nav_order: 1
---

# API routes

REST API served by **`openfdd-bridge`** (default `http://127.0.0.1:8765`). Production: Caddy on `:80` proxies to the bridge.

**OpenAPI:** `GET /docs` and `GET /redoc` when the bridge runs.

**Auth:** JWT via `POST /api/auth/login`. Most routes require `Authorization: Bearer <token>`. Roles: `viewer`, `operator`, `integrator`, `commission`, `agent`, `admin`. BACnet writes require commission role + [write safety](../bacnet/write-safety). Dev: `OFDD_AUTH_DISABLED` on loopback only.

**WebSocket:** `WS /ws/dashboard` — `POST /api/auth/ws-ticket`, then pass the ticket via `Sec-WebSocket-Protocol: ofdd.ws, <ticket>`. Query `?ticket=` is dev-only when `OFDD_WS_ALLOW_QUERY_TICKET=1`. Tickets are short-lived and not interchangeable with the Bearer token.

---

## Health & audit

| Method | Path | Role | Description |
|--------|------|------|-------------|
| GET | `/health` | public | Minimal liveness (`ok`, `service`, `version`, `auth_required`) |
| GET | `/health/stack` | auth | Stack traffic-light (verbose URLs/bind with `OFDD_DEBUG_DIAGNOSTICS`) |
| POST | `/api/auth/ws-ticket` | auth | Short-lived WebSocket ticket |
| GET | `/api/audit/summary` | auth | Audit counters |
| GET | `/api/audit/events` | auth | Audit log (query params) |
| GET | `/api/audit/errors` | auth | Recent API errors |

\*Exact public set depends on `OFDD_AUTH_DISABLED` and middleware.

---

## Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Username/password → JWT |
| GET | `/api/auth/me` | Current user |
| GET | `/api/auth/status` | Auth mode / lockout hints |

---

## Rules & FDD

| Method | Path | Role | Description |
|--------|------|------|-------------|
| GET | `/api/rules/saved` | user | Rule index |
| POST | `/api/rules/save` | operator+ | Create/update rule metadata |
| GET | `/api/rules/saved/{id}/source` | user | Python source |
| PUT | `/api/rules/saved/{id}/source` | operator+ | Write `.py` file |
| GET | `/api/rules/assignments` | user | Point bindings |
| POST | `/api/rules/bind` | integrator+ | Bind rule to point |
| POST | `/api/rules/bindings` | integrator+ | Bulk bindings |
| POST | `/api/rules/batch` | operator+ | Run all enabled rules → `fdd_results.json` |
| GET/POST | `/api/rules/drafts` | user | Draft rules |

---

## Rule Lab playground

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/playground/lint` | AST lint Python rule |
| POST | `/api/playground/test-rule` | Run `apply_faults_arrow()` on feather PyArrow window |
| POST | `/api/playground/run-script` | Execute script mode |
| GET | `/api/playground/sample-frame` | Sample DataFrame for editor |

---

## BRICK / data model

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/model/sites` | Site list |
| GET | `/api/model/tree` | Equipment tree (SPARQL) |
| GET | `/api/model/graph` | RDF graph fragment |
| GET | `/api/model/scope` | Scoped query |
| GET | `/api/model/export` | Export TTL/JSON |
| GET | `/api/model/health` | Model point/equipment counts |
| GET | `/api/model/ttl` | TTL metadata |
| POST | `/api/model/sync-ttl` | Regenerate TTL from JSON |
| POST | `/api/model/import` | Import model payload |
| POST | `/api/model/sites` | Create site |
| GET/POST | `/api/model/bacnet-sync` | BACnet ↔ model sync state |

---

## BACnet

| Method | Path | Role | Description |
|--------|------|------|-------------|
| GET | `/config/bacnet` | read | Commission URL / config |
| GET | `/api/bacnet/commission/status` | read | Commission agent health |
| GET | `/api/bacnet/server/points` | read | Server point table |
| GET | `/api/bacnet/inventory` | read | Discovered inventory |
| POST | `/api/bacnet/whois` | commission | Who-Is |
| POST | `/api/bacnet/discover` | commission | Discover devices |
| POST | `/api/bacnet/read` | commission | Read property |
| POST | `/api/bacnet/read-multiple` | commission | RPM read |
| POST | `/api/bacnet/write` | write | Supervisory write (gated) |
| POST | `/api/bacnet/import-to-model` | integrator | Inventory → BRICK |
| POST | `/api/bacnet/driver/sync-discovery` | commission | Sync driver tree |
| POST | `/api/bacnet/poll/once` | commission | Trigger poll cycle |
| GET | `/api/bacnet/poll/status` | read | Poll worker status |
| POST | `/ingest/bacnet` | read | Ingest samples into feather |

Bind address: `BACNET_BIND` in commission env — see [BACnet network setup](../bacnet/network-setup). Operator guide: [Discover and read](../bacnet/discover-read).

| PATCH | `/api/bacnet/driver/point` | commission | Enable poll + interval on point |
| PATCH | `/api/bacnet/driver/device` | commission | Enable poll for all points on device |
| PATCH | `/api/bacnet/driver/device/remap` | commission | Change instance and/or address |
| DELETE | `/api/bacnet/driver/point/{point_id}` | commission | Remove point from registry |
| DELETE | `/api/bacnet/driver/device/{device_instance}` | commission | Remove device |
| DELETE | `/api/bacnet/driver/registry` | commission | Clear CSVs + model sync |

---

## Faults (check-engine)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/faults/catalog` | Fixed fault codes |
| GET | `/api/faults/status` | GREEN/YELLOW/RED aggregate |
| GET | `/api/faults/tree` | Fault tree by equipment |
| GET | `/api/faults/code/{code}` | Code metadata |

---

## Timeseries & sites

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/timeseries/sites` | Feather sites |
| GET | `/api/timeseries/series` | Series metadata |
| GET | `/api/timeseries/plot` | Plot payload |
| GET | `/api/timeseries/readings` | Raw readings |
| GET | `/api/sites` | Site list |
| GET | `/api/sites/{site_id}/frame` | Wide frame for site |

---

## Building & host

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/building/status` | Building summary |
| GET | `/api/building/alerts` | Active alerts |
| GET | `/api/host/stats` | CPU/mem/disk |

---

## Local agent (Ollama)

Prefix **`/openfdd-agent`**. Role **`agent`** for tool execution.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/openfdd-agent/context` | Composed prompt context |
| GET | `/openfdd-agent/tools` | Tool manifest |
| POST | `/openfdd-agent/tool` | Execute tool (e.g. `rules.save`) |
| GET | `/openfdd-agent/ollama/health` | Ollama reachability |
| GET | `/openfdd-agent/building-insight` | Check-engine narrative context |
| GET | `/openfdd-agent/zone-temps` | Zone temperature insight |
| POST | `/openfdd-agent/chat` | Chat completion (catalog-bound) |

Optional host Ollama for building insight — not required for core FDD. Configure via compose profile or host service; see [Architecture overview](../architecture/overview).

---

## Modbus

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/modbus/read_registers` | Read holding registers |

---

## PyPI engine API (separate)

Library-only HTTP is **not** bundled. See [Python package](python-package) for `RuleRunner` and `open_fdd.reports`.

---

## Errors

JSON error bodies; stack traces hidden unless `OFDD_DEBUG_TRACEBACKS=1`. See [LAN hardening](../security/lan-hardening).
