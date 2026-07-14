# DIY BACnet Server — Open-FDD field-bus sidecar (pure Rust)

A turnkey **Rust axum** field-bus sidecar for [Open-FDD](https://github.com/bbartling/open-fdd).
It owns *all* field-bus I/O so the FDD app only ever speaks JSON:

- **rusty-bacnet** (native) — hosts BACnet server device **599999** on UDP `:47808`
  with Open-Meteo weather objects (20-min refresh) + diagnostic points, runs a
  **background poll engine**, **and** provides the full BACnet client toolkit
  (read, write, RPM, Who-Is, discovery, priority-array, supervisory override audit).
- **rusty-modbus** (native) — Modbus TCP read API.
- **rusty-haystack** (native) — read-only Haystack client (SCRAM or HTTP Basic for Niagara).

The HTTP layer is **axum + serde + validator + utoipa** — pure Rust, no Python runtime.
Native routes live at the root (`/bacnet/*`, `/modbus/*`, `/haystack/*`, `/weather`);
the same operations are mirrored under **`/api/*`** so Open-FDD can poll the sidecar
the way it does in production.

## Open-FDD sidecar model

Open-FDD contends for UDP `:47808` when it embeds its own BACnet stack. Running
this sidecar lets Open-FDD delegate every network request — BACnet, Modbus,
Haystack — and consume JSON only. The sidecar:

- owns the field bus (poll loop + on-demand client ops) and the hosted server;
- aligns the hosted weather objects to Open-FDD's instance map
  (`outside-air-temperature/humidity/dewpoint` = AV `9101/9102/9103`);
- honors `OPENFDD_FIELDBUS_*` environment variables (with the original
  `RUSTY_GATEWAY_*` names as fallbacks);
- exposes `/api/health` with `git_sha`/service shape and a write-safety
  **dry-run / approval** gate for supervised writes.

## Quick start (local dev)

Requires sibling checkouts: `../rusty-bacnet`, `../rusty-haystack`.

```bash
cd diy-bacnet-server
cp .env.example .env          # set OPENFDD_FIELDBUS_API_KEY, BIND, etc.
chmod +x scripts/*.sh

cd rust-api
cargo build --release
OPENFDD_FIELDBUS_CONFIG_DIR=../config cargo run --release
# Swagger: http://127.0.0.1:8080/docs
```

`scripts/preflight_free_47808.sh` frees UDP `:47808` before the server binds.

## Docker (long-running deployment)

Build context must be the **parent** directory containing `rusty-bacnet`,
`rusty-haystack`, and `diy-bacnet-server`:

```bash
cd diy-bacnet-server
cp .env.example .env
docker compose up -d --build
docker compose logs -f
```

The Rust image includes `tshark` for in-container PCAP validation.

## Bench validation

Modeled on `open-fdd/scripts/smoke_live_fdd_validation.sh` (30m BACnet/Modbus/Haystack cycles).

**Sidecar startup** (`.env`): API key, `OPENFDD_FIELDBUS_BIND`, Haystack upstream (`HAYSTACK_*`).

**Test targets** (scripts): Modbus host/port and BACnet device IDs are passed in REST POST
bodies — see `scripts/bench.env.example`.

```bash
cp scripts/bench.env.example scripts/bench.env.local   # optional overrides
chmod +x scripts/*.sh

# Fast smoke (REST + BACnet client on device 5007, P8=55% on AO:2466)
OPENFDD_FIELDBUS_API_KEY=... scripts/smoke_test.sh

# Full bench: per-feature BACnet PCAP + Modbus @ 192.168.204.14:1502 + Haystack Niagara
OPENFDD_FIELDBUS_API_KEY=... scripts/bench_test.sh

# Half-hour soak (like open-fdd 30m smoke)
BENCH_MINUTES=30 BENCH_INTERVAL_SECS=60 OPENFDD_FIELDBUS_API_KEY=... scripts/bench_test.sh

# Smoke + bench gate (CI / pre-merge)
OPENFDD_FIELDBUS_API_KEY=... scripts/openfdd_bench_gate.sh

# Open-FDD / VOLTTRON-style /api/* poll cycles
OPENFDD_FIELDBUS_API_KEY=... scripts/openfdd_platform_driver.sh
```

Haystack against Niagara requires sidecar env:

```bash
HAYSTACK_BASE_URL=https://192.168.204.11/haystack
HAYSTACK_USER=open_fdd
HAYSTACK_PASS=...
HAYSTACK_AUTH_MODE=basic
```

See [`docs/rust-migration-report.md`](docs/rust-migration-report.md) for the full route map.

## Design

The hosted server and the client use **separate sockets**. The server binds
`0.0.0.0:47808` so it receives broadcast Who-Is from BMS discovery tools, while
the client sends Who-Is on `:47808` and performs unicast reads on ephemeral
ports.

Set **`OPENFDD_FIELDBUS_BACNET_PORT`** when the building uses a non-default BACnet UDP port.

## Services

| Service | What it does |
|---------|--------------|
| **BACnet server** | Hosts device 599999 on `:47808` with weather + diagnostic objects. |
| **BACnet client** | Read / write / RPM / Who-Is / discovery / priority-array / supervisory against field devices. |
| **Weather** | Polls Open-Meteo, caches it, and mirrors it into BACnet objects. |
| **Modbus** | Batched Modbus TCP register reads with decode / scale / offset. |
| **Haystack** | Read-only Haystack client (about / read / nav / hisRead). |

## API (Bearer `OPENFDD_FIELDBUS_API_KEY` when set)

**BACnet client (field bus)**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/bacnet/read` | ReadProperty on a field device |
| POST | `/bacnet/write` | WriteProperty (priority + Null release; `approved:false` ⇒ dry-run) |
| POST | `/bacnet/write-dry-run` | Validate + encode a write without touching the bus |
| POST | `/bacnet/rpm` | ReadPropertyMultiple |
| POST | `/bacnet/whois` | Who-Is range scan |
| POST | `/bacnet/whois-router` | Who-Is router-to-network (routed networks) |
| POST | `/api/bacnet/point-discovery` | Point discovery (object-list + commandable scan) |
| POST | `/bacnet/priority-array` | Read a priority array (16 slots) |
| POST | `/bacnet/supervisory` | Supervisory override audit |
| GET | `/bacnet/poll/status` | Background poll engine status + last values |
| POST | `/bacnet/poll/once` | Run one poll cycle now (present-value, all points) |

Every row above is also served under `/api/bacnet/*` where applicable.
`/api/bacnet/supervisory` mirrors `/bacnet/supervisory`, and `/api/health` mirrors
`/bacnet/supervisory`, and `/api/health` mirrors `/health` with the Open-FDD shape
(`service`, `version`, `git_sha`, `poll_running`).

**BACnet server (hosted device 599999)**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/bacnet/server/objects` | Read all hosted points (`present_value`, `commandable`, `api_writable`) |
| GET | `/bacnet/server/commandable` | Read commandable (BACnet-writable) points and their current values |
| POST | `/bacnet/server/update` | Update **server-owned** points (commandable points are rejected) |

**Weather / Modbus / Haystack**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/weather` | Open-Meteo cache + BACnet mirror status |
| POST | `/weather/refresh` | Force a weather poll |
| POST | `/modbus/read` | Modbus TCP batch read |
| GET | `/haystack/about` | Haystack about |
| POST | `/haystack/read` | Haystack read (read-only) |
| POST | `/haystack/nav` | Haystack nav |
| POST | `/haystack/his-read` | Haystack hisRead |
| GET | `/health` | Liveness |

## Configuration

- `config/objects.csv` — hosted server point catalog.
- `config/field_devices.toml` — client field devices + points.
- `config/gateway.toml` — server / client bind + broadcast + timeouts.

See [Environment](docs/environment.md) for the full variable list.

## Validation scripts

| Script | Purpose |
|--------|---------|
| `scripts/smoke_test.sh` | Full REST + BACnet bench gate (device 5007 P8=55%) |
| `scripts/openfdd_platform_driver.sh` | Open-FDD / VOLTTRON-style `/api/*` poll cycles |
| `scripts/openfdd_bench_gate.sh` | Smoke + driver + PCAP capture |
| `scripts/soak_test.sh` | 30-minute sustained load test |

## Security

Optional `OPENFDD_FIELDBUS_API_KEY` enables Bearer middleware on protected routes;
`/`, `/health`, `/api/health`, and Swagger stay public.

## Remote access, Swagger, and OpenAPI

**Login** is Bearer API-key auth (not username/password). Set a strong key in `.env`:

```bash
OPENFDD_FIELDBUS_API_KEY=$(openssl rand -hex 32)
OPENFDD_FIELDBUS_HTTP_HOST=0.0.0.0
OPENFDD_FIELDBUS_HTTP_PORT=8080
```

From another machine on the network:

| URL | Purpose |
|-----|---------|
| `http://<host>:8080/docs` | **Swagger UI** — browse and try endpoints (click **Authorize**, paste your API key) |
| `http://<host>:8080/openapi.json` | **OpenAPI 3.1** spec (JSON) — generate TypeScript/Python clients |
| `http://<host>:8080/api/health` | Open-FDD liveness (no auth required) |

Protected routes need: `Authorization: Bearer <your-api-key>`

Optional: set `OPENFDD_FIELDBUS_SWAGGER_SERVERS_URL=http://192.168.x.x:8080` so Swagger "Try it out" hits your bench IP instead of `localhost`.

## Tests

```bash
cd rust-api && cargo test && cargo clippy -- -D warnings
```

Live bench (optional): `OPENFDD_FIELDBUS_API_KEY=... scripts/bench_test.sh`

### Remote Windows client

From your Windows machine (Rust installed), clone the repo and run the standalone bench client — no sibling `rusty-bacnet` deps:

```powershell
cd diy-bacnet-server\remote-bench
$env:FIELDBUS_BASE = "http://192.168.204.55:8080"
$env:OPENFDD_FIELDBUS_API_KEY = "bench-demo-key-1234567890"
cargo run --release
```

**Swagger:** `http://192.168.204.55:8080/docs` — Authorize with the same API key.  
**OpenAPI:** `http://192.168.204.55:8080/openapi.json`

See [`remote-bench/README.md`](remote-bench/README.md).
