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

  The **3.2 Rust edge** is a single, memory-safe runtime: JWT auth, React dashboard, Apache Arrow historian, DataFusion SQL FDD, BACnet/Modbus/Haystack drivers, and Docker/GHCR lifecycle scripts. Rust gives predictable latency, strong typing at the OT boundary, and one binary per service — no Python interpreter on the edge path.

  Includes an open knowledge layer for AI-assisted building diagnostics, commissioning support, and HVAC fault investigation.
</p>

## Architecture

Open-FDD uses **Apache Arrow** and **Feather** as the native historian and data storage layer, while **DataFusion SQL** serves as the fault detection and analytics engine that operates directly on those Arrow datasets. Rather than storing building telemetry in a traditional relational database, data collected from BACnet, Haystack, Modbus, and JSON APIs is normalized into Arrow-native structures and persisted as Feather files, allowing high-performance columnar analytics at the edge. DataFusion then executes SQL-based fault detection rules, reporting logic, and data quality checks directly against the Arrow historian — a clear path toward a fully Rust-based analytics stack without Pandas or other row-oriented processing frameworks.

The platform is migrating to an **all-Rust architecture**: protocol drivers, historian services, APIs, and the analytics engine. BACnet communication uses Rust-native BACnet libraries; Haystack support is implemented through Rust Haystack integrations; Modbus connectivity uses Rust Modbus libraries; and the FDD engine executes DataFusion SQL against Arrow datasets. The entire telemetry pipeline stays memory-safe, performant, and suitable for resource-constrained edge devices as well as larger on-premises building servers.

Open-FDD deploys as a collection of **Docker containers** that work together as a complete edge operations platform:

| Container | Role |
| --- | --- |
| **openfdd-bridge** | REST API, JWT auth, Arrow historian, React dashboard, Modbus driver, JSON API sources, agent APIs |
| **openfdd-commission** | BACnet discovery, point browsing, polling, supervisory override scans |
| **openfdd-haystack-gateway** | Project Haystack read/nav/ops against BAS stations (Niagara-style integration path) |

The left **Driver Tree** in the dashboard lists BACnet, Modbus/TCP, JSON API, and Haystack gateway entries from `workspace/data/drivers/bacnet/driver_tree.json`. Modbus, JSON API, and Haystack also expose dedicated REST routes on the bridge (`/api/modbus/*`, `/api/json-api/*`, `/api/haystack/*`, `/api/model/haystack`). MCP and knowledge services are planned; agent JSON APIs are already on the bridge.

Together these services create a self-hosted, on-premises platform for building telemetry collection, data modeling, fault detection and diagnostics, retro-commissioning, and AI-assisted building operations — without a cloud dependency.

See [architecture overview](docs/architecture/overview.md) and [drivers + FDD](docs/architecture/drivers-and-fdd.md).

<p align="center">
  <a href="docs/README.md"><img src="https://img.shields.io/badge/Documentation-read_online-2563EB?style=for-the-badge" alt="Documentation"></a>
  <a href="docs/quick-start/rust-edge-bootstrap.md"><img src="https://img.shields.io/badge/Quick%20Start-Rust%20Edge-059669?style=for-the-badge" alt="Rust quick start"></a>
  <a href="https://github.com/bbartling/open-fdd/blob/master/pdf/open-fdd-docs.pdf"><img src="https://img.shields.io/badge/Legacy%20PDF-Python%20era-DC2626?style=for-the-badge" alt="Legacy PDF"></a>
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

Open `http://127.0.0.1:8080` — sign in with **integrator** credentials from `~/open-fdd/workspace/auth.env.local` (password never printed by bootstrap).

### Update an existing site

```bash
cd ~/open-fdd
./scripts/openfdd_rust_site_backup.sh
./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_edge_validate.sh
```

**Never** run `docker compose down -v`. **Never** delete `workspace/`.

See [Rust site lifecycle](docs/quick-start/rust-site-lifecycle.md).

### Production TLS (Caddy + auth)

For lab pen-tests or LAN deployment behind TLS, build from source with Caddy:

```bash
# Generate auth if missing (once)
cd edge && cargo run --release --bin openfdd_edge -- auth init --path ../workspace/auth.env.local
chmod 600 ../workspace/auth.env.local

docker compose -f docker-compose.prod.yml up -d --build
./scripts/openfdd_prod_validate.sh
```

- HTTPS: `https://127.0.0.1/` (self-signed via Caddy `tls internal`)
- API health: `curl -kfsS https://127.0.0.1/api/health`
- Bridge is **not** exposed on `:8080` to the host — only via Caddy `:443`

Bind to Tailscale or a firewall-restricted interface for remote pen-testing; do not expose MCP or the dashboard to the public internet.

---

## AI Agent Prompt

| Area | Examples |
|------|----------|
| **Edge deploy** | `openfdd_rust_edge_bootstrap.sh`, `openfdd_rust_site_backup.sh`, `openfdd_rust_site_update.sh`, `openfdd_rust_check_ghcr_platform.sh`, health checks |
| **Drivers** | BACnet discover/poll/bind, Modbus scan/read, JSON API endpoints, driver tree |
| **Model & rules** | Haystack model, FDD Wires graph, DataFusion SQL rules, batch FDD, assignment proposals |
| **Operations** | Building check-in, override scans, stack health, Arrow/DataFusion demos |
| **Reports** | RCX plan/generate (prototype endpoints) |
| **Safety** | No BACnet writes without approval; never `docker compose down -v`; never delete `workspace/` |

Deeper route maps: [AI agent guide](docs/ai-agent/README.md) · [SQL FDD cookbook](docs/rule-cookbook/sql-hvac-fdd.md) · [Haystack AI modeling](docs/ai-agent/haystack-and-assignments.md) · [AGENTS.md](AGENTS.md) · [verification checklists](docs/verification/)

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
4. Auth is configured (workspace/auth.env.local).
5. Integrator login succeeds.
6. The install is safe for a local OT/LAN edge box and is not exposed publicly.

Important project facts:
- Open-FDD 3.2 edge is 100% Rust — use openfdd_rust_edge_bootstrap.sh, not the legacy Python bootstrap.
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

Step 5 — Login smoke (do not print password or token)
Use integrator user from workspace/auth.env.local

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
- expose bridge to 0.0.0.0 on the public internet

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

Contributor layout: [AGENTS.md](AGENTS.md) · [docs/README.md](docs/README.md)

| Component | Technology |
| --- | --- |
| API + auth | Rust (`edge/`) — JWT, RBAC, audit |
| UI | React static assets |
| Historian | Apache Arrow RecordBatches |
| FDD | DataFusion SQL + confirmation duration |
| BACnet | rusty-bacnet (live) or simulated |
| Modbus | Native Rust TCP client |
| Publish | GHCR multi-arch (`rust-ghcr.yml`) |

---

## Legacy Python stack (3.1.x — compatibility only)

The pre-Rust edge used separate Python images (`openfdd-bridge`, `openfdd-commission`, `openfdd-mcp-rag`) on port **8765** and a PyPI `open-fdd` package. That line remains in git history for reference; **new deployments should use the Rust GHCR image above**.

PyPI embeddable runtime (optional, off-edge):

```bash
pip install open-fdd
```

See legacy docs PDF and [bbartling.github.io/open-fdd](https://bbartling.github.io/open-fdd/) for Python-era cookbooks.

---

## License

MIT — see [LICENSE](LICENSE).

Version: **3.2.0**
