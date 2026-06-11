---
title: JSON API driver
parent: Driver framework
nav_order: 3
---

# JSON API driver

Poll **HTTP or HTTPS** REST endpoints on the OT LAN (or public APIs such as [OpenWeatherMap](https://openweathermap.org/api)) and store extracted JSON values in the feather historian (`source=json_api`).

Use this driver for gateways, micro-PLCs, IoT hubs, vendor APIs, and **web weather** when you want to cross-check shaky local outdoor-air sensors against a reference.

## Supported features

| Feature | Support |
|---------|---------|
| Methods | `GET`, `POST` |
| Transport | `http://` and `https://` |
| TLS certificate verify | On by default; disable for self-signed OT gateways |
| Authentication | None, **Bearer token**, **HTTP Basic**, or **query-string API keys via env** |
| Env placeholders | `${ENV:VAR}` or `${VAR}` in URL, headers, body, bearer token |
| Custom headers | Optional `headers` map (merged with auth headers) |
| Value extraction | Dot-path into JSON body (`title`, `main.temp`, `weather.0.description`) |
| Multi-extract poll | One HTTP request per URL group; fan-out to multiple `json_path` rows |
| Polling | **1 / 5 / 15 / 30 min** or **1 hour** (shared with BACnet/Modbus) |
| Historian | `workspace/json_api/polls/samples.csv` → `feather_store/json_api/` |
| FDD merge | Scheduled FDD merges `bacnet` + `modbus` + `json_api` columns by nearest timestamp |

## Secrets: `json_api.env.local`

Copy `workspace/json_api.env.example` → `workspace/json_api.env.local` (gitignored). The bridge loads this file at startup and when `run_local.sh` starts the stack.

Use placeholders in commissioning URLs so API keys never land in git:

```text
https://api.openweathermap.org/data/2.5/weather?q=${ENV:OPENWEATHER_CITY}&appid=${ENV:OPENWEATHER_API_KEY}&units=${ENV:OPENWEATHER_UNITS}
```

Check which vars are configured: `GET /api/json-api/env/status`.

## OpenWeatherMap showcase (recommended demo)

This is the flagship example of what the generic JSON API driver can do — **one URL, three historian columns**, env-based API key, browser tree like BACnet/Modbus.

### 1. Configure env

```bash
cp workspace/json_api.env.example workspace/json_api.env.local
# Edit: OPENWEATHER_API_KEY, OPENWEATHER_CITY, OPENWEATHER_UNITS (imperial = °F)
```

Restart the bridge (or `./scripts/run_local.sh restart`) so env vars load.

### 2. Register from the UI

1. Sign in as **integrator** → **JSON API** tab.
2. Open the **OpenWeatherMap showcase** panel.
3. Use the **OpenWeatherMap** preset → **Register** (default poll 30 min; choose interval in the form).

Three endpoints appear under `api.openweathermap.org` in the commissioning tree:

| Label | JSON path | Historian column | Units |
|-------|-----------|------------------|-------|
| web-oat-t | `main.temp` | `web-oat-t` | degF / degC |
| web-rh | `main.humidity` | `web-rh` | % |
| web-weather-desc | `weather.0.description` | `web-weather-desc` | text |

Poll worker deduplicates: **one GET** serves all three extractions per cycle.

### 3. Headless / script

```bash
# Standalone fetch (like the original playground tester)
python3 scripts/openweather_json_api_example.py

# Register via REST (integrator login)
python3 scripts/openweather_json_api_example.py --register --base http://127.0.0.1:8000
```

### 4. FDD: local OA-T vs web weather

With BACnet `oa-t` and JSON API `web-oat-t` in the merged site frame, scheduled FDD compares local outdoor air to the weather service.

| Item | Detail |
|------|--------|
| Rule module | `oat_vs_web_spread_1h.py` |
| Fault code | **BLD-B** (outdoor air sensor fault) |
| Default threshold | `|oa-t − web-oat-t| > 8 °F` (`max_spread_f` in rule cfg) |
| Acme rule id | `acme-oat-vs-web-spread` (via `setup_gl36_fdd.py`) |
| Local OAT source | RTU `1100-unknown-2` (Outdoor Air Temperature Local) — same value as boiler/AHU networked OAT |
| Web column | `web-oat-t` from OpenWeather bundle |

**Model alias:** local BACnet historian column must be `oa-t`:

```bash
python3 scripts/acme_patch_oat_column.py --point-id 1100-unknown-2 --host "$ACME_HOST" --token "$TOKEN"
```

Or set `external_id` / `fdd_input` to `oa-t` on the chosen `Outside_Air_Temperature_Sensor` in the model.

**Units:** keep `OPENWEATHER_UNITS=imperial` when BACnet OAT is °F.

Enable the rule in Rule Lab (or `setup_gl36_fdd.py` push) and run an FDD batch. Missing either column → rule returns all-false (no crash).

## Commissioning (UI)

The **JSON API** tab follows [Home Assistant `sensor.rest`](https://www.home-assistant.io/integrations/sensor.rest/):

1. Sign in → **RESTful sensor (JSON API)** tab.
2. Pick a **preset** (JSONPlaceholder, DummyJSON, httpbin, Open-Meteo, OpenAQ, OpenWeather) or enter a **resource URL**.
3. Add one or more **sensors** — each row is a `value_json_path` + historian **label** (multi-value from one GET, like HA `json_attributes`).
4. Click **Test resource** — probes without saving; shows extracted values and raw JSON.
5. Click **Register & poll** — writes `endpoints.csv`, enables polling at the selected interval.
6. Poll choices match BACnet/Modbus: **1 / 5 / 15 / 30 min** or **1 hour**.

### API for agents

| Endpoint | Purpose |
|----------|---------|
| `GET /api/json-api/presets` | Full preset catalog + poll intervals (human + AI readable) |
| `POST /api/json-api/test` | Probe resource + multi-sensor extraction |
| `POST /api/json-api/register-bundle` | Register one resource with many sensors |
| `POST /api/json-api/presets/{id}/register` | One-click preset registration |

### Bench preset

Use **JSONPlaceholder — todo title** → **Test resource** to verify outbound HTTPS without field hardware.

## Authentication examples

### Query-string API key via env (OpenWeather)

```json
{
  "url": "https://api.openweathermap.org/data/2.5/weather?q=${ENV:OPENWEATHER_CITY}&appid=${ENV:OPENWEATHER_API_KEY}&units=${ENV:OPENWEATHER_UNITS}",
  "method": "GET",
  "json_path": "main.temp",
  "label": "web-oat-t",
  "auth_type": "none"
}
```

### Bearer token (API key)

```json
{
  "url": "https://192.168.10.50/api/v1/status",
  "method": "GET",
  "json_path": "sensors.zone_temp",
  "label": "zone-temp",
  "auth_type": "bearer",
  "bearer_token": "${ENV:GATEWAY_API_KEY}",
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

Credentials in `endpoints.csv` are redacted in API responses (`***`). Prefer `${ENV:…}` for production keys.

## REST API

| Method | Path | Role | Description |
|--------|------|------|-------------|
| GET | `/api/json-api/env/status` | operator+ | Which env vars are configured (no secret values) |
| POST | `/api/json-api/presets/openweather` | integrator+ | Register 3-point OpenWeather bundle + optional poll |
| GET | `/api/json-api/driver/tree` | operator+ | Commissioning tree grouped by host |
| GET | `/api/json-api/poll/status` | operator+ | Poll worker status |
| POST | `/api/json-api/poll/once` | integrator+ | Run one poll cycle |
| POST | `/api/json-api/request` | operator+ | One-shot HTTP request (no store) |
| POST | `/api/json-api/read_and_store` | integrator+ | Request + CSV + feather ingest |
| POST | `/api/json-api/refresh` | operator+ | Re-fetch one endpoint |
| PATCH | `/api/json-api/endpoint/poll` | integrator+ | Enable/disable poll interval |
| DELETE | `/api/json-api/endpoint/{point_id}` | integrator+ | Remove endpoint |

Full route list: [API routes]({% link appendix/bridge_api.md %}).

## Typical OT URLs

| Device type | Example URL | Notes |
|-------------|-------------|-------|
| Web weather | `https://api.openweathermap.org/data/2.5/weather?...` | Env-based `appid`; 3 historian columns |
| Gateway status | `http://192.168.1.50/api/status` | Often plain HTTP on LAN |
| HTTPS BMS API | `https://10.0.0.12/rest/points/zone1` | May need `verify_tls: false` |
| Local mock | `https://jsonplaceholder.typicode.com/todos/1` | Bench / CI only |

## Limitations

- Response body must be **JSON** (not XML or plain text).
- Numeric paths (e.g. `main.temp`) are stored as strings in poll CSV; FDD rules cast with `pc.cast(..., "float64")`.
- Outbound requests originate from the **bridge** container/host — ensure routing and firewall rules allow the edge box to reach the target (OT subnet or public internet for weather).

## Disable polling (save API quota)

Stop scheduled calls without deleting endpoints: JSON API tree → select OpenWeather points → **Stop polling**, or integrator API:

```bash
curl -X PATCH http://127.0.0.1:8765/api/json-api/endpoint/poll \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"point_id":"ja-api-openweathermap-org-get-web-oat-t","enabled":false,"poll_interval_s":0}'
```

API keys live in `json_api.env.local` (gitignored) — never committed; audit logs do not record expanded URLs with `appid=`. See [Logging and audit]({% link ops/logging.md %}).

## Smoke test

```bash
python3 scripts/smoke_multi_driver_stack.py
```

Validates JSON API ingest alongside BACnet and Modbus, feather isolation, BRICK scope, and FDD batch.
