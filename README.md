# Open-FDD

<p align="center">
  <a href="https://discord.gg/Ta48yQF8fC"><img src="https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/bbartling/open-fdd/actions/workflows/ci.yml"><img src="https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master" alt="CI"></a>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT">
  <img src="https://img.shields.io/badge/status-Beta-blue" alt="Beta">
  <img src="https://img.shields.io/badge/Rust-1.93-orange?logo=rust&logoColor=white" alt="Rust 1.93">
  <img src="https://img.shields.io/badge/Apache%20Arrow-53-blue" alt="Arrow">
  <img src="https://img.shields.io/badge/DataFusion-SQL-purple" alt="DataFusion">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png" alt="Open-FDD logo" width="440">
</p>


<p align="center">
  Open-source HVAC supervisory fault detection for buildings — local-first, on-prem, vendor-neutral, and free to run at the edge.
</p>

<p align="center">
  The <strong>Open-FDD Rust edge</strong> includes JWT auth, a React dashboard, Apache Arrow/Feather historian, DataFusion SQL fault rules, BACnet/Modbus/Haystack drivers, reports, and Docker/GHCR lifecycle scripts.
</p>

<p align="center">
  Built for local building networks, Raspberry Pi / edge servers, and on-prem BAS integration without requiring a cloud service.
</p>

## Architecture

Open-FDD is a Rust-based edge application for building telemetry, supervisory fault detection, reporting, and HVAC diagnostics.

Telemetry from BACnet, Haystack, Modbus, JSON APIs, and CSV imports is normalized into an Arrow-native historian and persisted as Feather files. DataFusion SQL runs fault rules, validation checks, analytics, and report queries directly against that local historian.

<details>
<summary><strong>Service modes and driver locations</strong></summary>

Open-FDD currently publishes one Rust GHCR image:

```text
ghcr.io/bbartling/openfdd-edge-rust
```

Docker Compose can run that same image as multiple service containers by changing the service mode.

### `openfdd-bridge`

Main application service.

Responsibilities:

* Main REST API service
* React dashboard static serving
* JWT auth / RBAC
* Arrow / Feather historian
* DataFusion SQL FDD
* Reports / PDF generation
* Building dashboard summary APIs
* Fault analytics APIs
* Trend / timeseries APIs
* Data export / purge APIs
* Model and assignment APIs

Bridge-owned drivers:

#### Modbus driver

The Modbus driver currently lives in `openfdd-bridge` unless it is split into its own service later.

Responsibilities:

* Modbus/TCP connection config
* Modbus register reads
* Modbus poll status
* Modbus driver tree API

Example routes:

```text
/api/modbus/driver/tree
/api/modbus/poll/status
/api/modbus/read
/api/modbus/poll-once
```

#### JSON API driver

The JSON API driver currently lives in `openfdd-bridge` unless it is split into its own service later.

Responsibilities:

* REST/JSON source config
* HTTP polling
* JSON path/value mapping
* JSON API poll status
* JSON API driver tree API

Example routes:

```text
/api/json-api/driver/tree
/api/json-api/poll/status
/api/json-api/poll-once
```

### `openfdd-commission`

BACnet-specific service mode.

Responsibilities:

* BACnet discovery / Who-Is
* BACnet point browsing
* BACnet polling
* BACnet driver tree generation
* BACnet override scans
* BACnet priority-array checks
* BACnet CSV artifacts for override summaries

Example routes or APIs exposed through bridge/service wiring:

```text
/api/bacnet/driver/tree
/api/bacnet/overrides/scan-once
/api/bacnet/poll/status
```

### `openfdd-haystack-gateway`

Haystack-specific service mode.

Responsibilities:

* Project Haystack read/nav/ops
* Niagara nHaystack integration path
* Haystack source browsing
* Haystack point reads
* Haystack model/source import
* Haystack-to-Open-FDD model mapping

Example routes:

```text
/api/haystack/status
/api/haystack/about
/api/haystack/ops
/api/haystack/nav
/api/haystack/read
/api/haystack/import
/api/haystack/driver/tree
/api/model/haystack
```

### Future service mode

MCP / agent tooling is expected to become a later service mode after the core Rust edge, drivers, historian, FDD, and reports are stable.

Possible future shape:

```text
openfdd-mcp
```

or:

```text
SERVICE_MODE=mcp
```

</details>


<p align="center">
  <a href="docs/README.md">
    <img src="https://img.shields.io/badge/Docs-online-2563EB?style=for-the-badge" alt="Online docs">
  </a>
  <a href="docs/quick-start/rust-edge-bootstrap.md">
    <img src="https://img.shields.io/badge/Quick%20Start-Rust%20Edge-059669?style=for-the-badge" alt="Rust edge quick start">
  </a>
  <a href="https://arrow.apache.org/">
    <img src="https://img.shields.io/badge/Apache%20Arrow-columnar%20data-0B7285?style=for-the-badge" alt="Apache Arrow">
  </a>
  <a href="https://datafusion.apache.org/">
    <img src="https://img.shields.io/badge/DataFusion-SQL%20engine-6D28D9?style=for-the-badge" alt="Apache DataFusion">
  </a>
</p>

---

## Install / run

### Full Open-FDD Rust edge stack (Docker / GHCR)

| Image | Role |
|-------|------|
| [`ghcr.io/bbartling/openfdd-edge-rust`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-edge-rust) | API, dashboard, historian, commission, Haystack (same image, `SERVICE_MODE`) |

GHCR publishes **multi-arch** images (`linux/amd64` + `linux/arm64`). Edge scripts **auto-detect** the host CPU.

| Host CPU (`uname -m`) | Docker platform | Typical hardware |
|-----------------------|-----------------|------------------|
| `x86_64`, `amd64` | `linux/amd64` | Intel/AMD servers, VMs |
| `aarch64`, `arm64` | `linux/arm64` | Raspberry Pi 4/5 (64-bit OS) |

Verify before pull (optional on Pi):

```bash
cd ~/open-fdd
./scripts/openfdd_rust_check_ghcr_platform.sh
```

### Manual installation (no git clone on device)

```bash
curl -fsSL -o /tmp/openfdd_rust_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_rust_edge_bootstrap.sh
bash /tmp/openfdd_rust_edge_bootstrap.sh --start
```

Open `http://127.0.0.1:8080` — sign in with **integrator** credentials from `workspace/bootstrap_credentials.once.txt` (password never printed by bootstrap).

### Update an existing site

```bash
cd ~/open-fdd
./scripts/openfdd_rust_site_backup.sh
./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_edge_validate.sh
```

---

## Agent prompts


<details>
<summary><strong>Copy-paste: OpenClaw — fresh Raspberry Pi Rust edge bootstrap</strong></summary>

Prompt tuned for **OpenClaw** on a new Pi. Edge deploy uses **GHCR Docker** (not a source clone): `ghcr.io/bbartling/openfdd-edge-rust`.

```text
You are OpenClaw running on a fresh Raspberry Pi intended to become an Open-FDD edge device.

Goal:
Install and bootstrap Open-FDD Rust edge from https://github.com/bbartling/open-fdd on this fresh Raspberry Pi, start the Docker edge stack, then validate that:
1. Docker is installed and working.
2. Open-FDD edge stack is running (bridge, commission, haystack-gateway).
3. Bridge health is good (GET /api/health).
4. Auth is configured.
5. Plaintext bootstrap credentials are available in workspace/bootstrap_credentials.once.txt if generated.
6. Integrator login succeeds using the plaintext bootstrap credentials.

Important project facts:
- Open-FDD 3.2 edge is a Rust edge runtime — use openfdd_rust_edge_bootstrap.sh, not the legacy Python bootstrap.
- Primary GHCR image: ghcr.io/bbartling/openfdd-edge-rust:latest
- Bootstrap script:
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_rust_edge_bootstrap.sh
- ARM64: verify GHCR manifest with openfdd_rust_check_ghcr_platform.sh
- Default site root: ~/open-fdd
- Persistent workspace: ~/open-fdd/workspace — never delete
- Never run docker compose down -v
- Do not print secrets into logs, Git commits, or chat

Work plan:

Step 0 — Identify host
Run: whoami; hostname; uname -a; uname -m; cat /etc/os-release; ip -4 addr show scope global

Step 1 — Install Docker if missing (official Docker apt repo for Debian/Pi OS)

Step 2 — GHCR architecture check on aarch64/arm64

Step 3 — Bootstrap
curl -fsSL -o /tmp/openfdd_rust_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_rust_edge_bootstrap.sh
bash /tmp/openfdd_rust_edge_bootstrap.sh --start

Step 4 — Validate
cd ~/open-fdd && docker compose ps
curl -sf http://127.0.0.1:8080/api/health | jq .
./scripts/openfdd_rust_edge_validate.sh

Step 5 — Login smoke

Use integrator credentials from workspace/bootstrap_credentials.once.txt if present.

Do not print passwords or tokens.
Do not use bcrypt hashes from auth.env.local as login passwords.

Final report: host summary, Docker status, container status, health, login pass/fail, next manual steps.
Stop if GHCR pull fails, bridge health never recovers, or auth file missing.
```

</details>

<details>
<summary><strong>Copy-paste: OpenClaw — ongoing edge operator (drivers + FDD)</strong></summary>

Use after bootstrap when the stack is healthy. Agent connects via bridge JWT on port 8080 (or HTTPS via Caddy in prod compose).

```text
You are OpenClaw maintaining an Open-FDD Rust edge site at ~/open-fdd.

Goal:
Help the human operator keep drivers, model, and FDD healthy — without BACnet writes unless explicitly approved.

You can:
- Check health: GET /api/health, GET /api/health/stack (JWT)
- Commission drivers: BACnet driver tree, Modbus points, JSON API sources
- FDD Wires: graphs, propose assignments, validate/approve/activate (integrator for activation)
- SQL rules: builder-sql, test-sql, validate-sql (DataFusion in Rust)
- Operations: building checkin, override scan/export, stack status
- Updates: openfdd_rust_site_backup.sh then openfdd_rust_site_update.sh

Never:
- docker compose down -v
- delete workspace/
- print passwords, tokens, or auth.env.local contents in chat
- expose the dashboard/API to the public internet

Start each session with integrator JWT login from workspace/auth.env.local.
Report faults, stale points, and recommended next steps in plain language.
```

</details>

<details>
<summary><strong>Copy-paste: OpenClaw — backup, update & restore</strong></summary>

Full reference: [Rust site lifecycle](docs/quick-start/rust-site-lifecycle.md).

```text
You are OpenClaw upgrading an Open-FDD Rust edge site at ~/open-fdd.

Goal:
Run a safe image upgrade with backup, Docker maintenance, validation, and backup purge — or restore workspace from backup if requested.

Standard upgrade:
  cd ~/open-fdd
  ./scripts/openfdd_rust_site_backup.sh
  ./scripts/openfdd_rust_site_update.sh
  ./scripts/openfdd_rust_edge_validate.sh

Useful env vars:
  NEW_TAG=latest                    GHCR tag (OPENFDD_IMAGE_TAG)
  OPENFDD_DOCKER_PLATFORM=auto      linux/arm64 | linux/amd64

If validation fails:
- Backup is kept
- Inspect: docker compose logs --since 10m openfdd-bridge
- Never docker compose down -v; never delete workspace/

Report: backup size, image tag, health pass/fail, whether backup was purged.
```

</details>

---

## Develop (Rust)

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
cp .env.example .env
docker compose up --build
# or
cargo test --workspace
cargo run -p open_fdd_edge_prototype
```

Production-style local stack with Caddy TLS:

```bash
docker compose -f docker-compose.prod.yml up -d --build
./scripts/openfdd_prod_validate.sh
```


## License

MIT — see [LICENSE](LICENSE).

Version: **3.2.0**
