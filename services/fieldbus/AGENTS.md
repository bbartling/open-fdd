# Agent instructions — DIY BACnet Server (Open-FDD field-bus)

This file is **durable project context**. Do not remove or bypass these rules when refactoring.

## Hosted BACnet device (device 599999 / OpenFDD)

The gateway hosts a BACnet/IP server on UDP **47808** (configurable via `OPENFDD_FIELDBUS_BACNET_PORT`).

| Requirement | Detail |
|-------------|--------|
| Device name | `OpenFDD` (`config/gateway.toml` → `device_name`) |
| Vendor ID | **999** on `BACnetServer::bip_builder().vendor_id(999)` **and** `DeviceConfig.vendor_id` |
| Model | `openfdd-fieldbus` |
| Point catalog | `config/objects.csv` — **do not drop rows** without explicit user request |

### Server vs client UDP sockets

- **Server** binds `0.0.0.0:47808` (or configured port) — only socket on that port.
- **Client** uses **ephemeral** UDP ports (`whois_bind_port = 0` in `gateway.toml`).
- Never bind the BACnet client to the same UDP port as the hosted server (causes Workbench `???` / dropped ReadProperty).

## REST vs BACnet write split (critical — no data races)

Points in `objects.csv` with **`Commandable=Y`** are **BACnet-writable only**:

- External BMS / Workbench / Niagara may WriteProperty (e.g. `openfdd-optimization-enabled` BV **9010**).
- REST **`POST /bacnet/server/update` must reject** writes to commandable points.
- Mechanism: `BacnetServerManager::api_writable()` / `reject_api_write()` in `rust-api/src/services/bacnet_server.rs`.
- Rejection message constant: `API_WRITABLE_REJECT_MSG`.

Points with **`Commandable=N`** are **server-owned** (weather mirror, FDD diagnostics). Only these may be updated via REST.

### Tests that must stay green

- `every_commandable_point_rejects_api_write`
- `optimization_enabled_is_only_commandable_hosted_point`
- `update_rejects_commandable_point`
- Smoke: `scripts/smoke_test.sh` hosted-server section (commandable reject + weather points)

## Weather mirror (Open-Meteo)

Weather AVs **9101–9104**, location CSV **9105**, fault BV **9106**, last-updated CSV **9107**.

On each mirror cycle, update:

1. **Present-value** on weather points
2. **Description** with live Open-Meteo context (value + timestamp + source)
3. **`weather-last-updated`** (CSV:9107) with human-readable timestamp

Implementation: `rust-api/src/services/weather.rs` → `mirror_to_bacnet()`.

## Before merging BACnet changes

1. `cargo test` in `rust-api/`
2. `scripts/smoke_test.sh` against running container
3. Optional: `point-discover --device 599999 --address <host>:47808` from rusty-bacnet samples — expect name **OpenFDD** and ≥10 objects

## Swagger / OpenAPI bench examples

- **`OPENFDD_FIELDBUS_SWAGGER_BENCH=1`** by default — bench JSON bodies always pre-filled (opt-out with `=0`).
- **Open-FDD workflow:** `POST /bacnet/whois` `{}` → `POST /api/bacnet/point-discovery` → `POST /api/bacnet/supervisory`.
- **`GET /bacnet/points` removed** — use Who-Is + point discovery instead.

## Key files

```
config/objects.csv          # hosted point catalog (+ Description column)
config/gateway.toml         # device 599999, server bind, client ephemeral ports
rust-api/src/services/bacnet_server.rs
rust-api/src/services/weather.rs
scripts/smoke_test.sh
```
