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
  <img src="https://raw.githubusercontent.com/bbartling/open-fdd/master/image_new_chiller.png" alt="Open-FDD logo" width="440">
</p>


> **Open-source semantic building analytics and HVAC supervisory fault detection. Local-first. On-premises. Vendor-neutral. Free to run at the edge or offline.**

Open-FDD Rust Edge is an open-source analytics platform for building automation systems that combines **semantic knowledge graph modeling**, **live operational technology (OT) data**, and **high-performance columnar analytics** into a single workflow.

The platform includes:

- Semantic building modeling using **Project Haystack** knowledge graphs
- JWT authentication and a modern React web interface
- Apache Arrow & Feather columnar data storage
- Apache DataFusion SQL analytics and fault detection
- BACnet, Modbus, Haystack, and JSON API drivers
- Interactive plotting, dashboards, and PDF reporting
- Deterministic CSV import, Haystack modeling, DataFusion SQL FDD, and reporting workflows
- Optional **external** agent integration via MCP stdio and JWT REST (no embedded chatbot)
- Docker and GitHub Container Registry deployment

Open-FDD supports two complementary deployment models.

### Live OT Edge

Deploy on Linux IoT edge systems located within client environments, including industrial PCs, virtual machines, or edge servers connected to building automation networks. These systems can be securely subnetted to operational technology (OT) LANs for direct communication with BACnet, Modbus, Haystack, and other building control protocols while remaining isolated from the public Internet.

### Offline Engineering & Analytics

Run Open-FDD in Docker on engineering workstations to perform offline analysis of exported building data. Engineers can import and combine CSV files from multiple vendors, normalize timestamps, append or merge datasets, visualize trends, build semantic models, execute DataFusion SQL fault detection rules, and generate reports—all without requiring a live connection to the building automation network.

Both deployment models share the same analytics engine, semantic data model, Apache Arrow storage format, and DataFusion SQL execution layer, allowing engineering workflows to move seamlessly between offline analysis and live edge deployments.

Open-FDD is designed to be **local-first**. No cloud services are required. External agents connect through optional MCP and REST while building telemetry, semantic models, and analytics stay under the owner's control.


<p align="center">
  <a href="https://bbartling.github.io/open-fdd/">
    <img src="https://img.shields.io/badge/Docs-online-2563EB?style=for-the-badge" alt="Online docs">
  </a>
  <a href="https://bbartling.github.io/open-fdd/quick-start/docker-ghcr.html">
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
| [`ghcr.io/bbartling/openfdd-edge-rust`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-edge-rust) | **Primary runtime** — bridge, dashboard, historian, commission, Haystack (`SERVICE_MODE`); **`openfdd-mcp`** binary (`docker run --entrypoint openfdd-mcp …`) |
| [`ghcr.io/bbartling/openfdd-mcp`](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-mcp) | **Optional slim MCP image** — same `openfdd-mcp` binary, stdio entrypoint only (smaller pull) |

Open-FDD does **not** ship an embedded AI chatbot or vendor-specific chat relay. External agents (Codex CLI, Cursor, Claude Desktop, OpenClaw, etc.) connect via MCP or REST — see [docs/examples/external-agents.md](docs/examples/external-agents.md).


GHCR publishes **multi-arch** images (`linux/amd64` + `linux/arm64`). Edge scripts **auto-detect** the host CPU.

| Host CPU (`uname -m`) | Docker platform | Typical hardware |
|-----------------------|-----------------|------------------|
| `x86_64`, `amd64` | `linux/amd64` | Intel/AMD servers, VMs |
| `aarch64`, `arm64` | `linux/arm64` | Raspberry Pi 4/5 (64-bit OS) |

Verify before pull (optional on Linux):

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
- Primary GHCR image: ghcr.io/bbartling/openfdd-edge-rust:3.2.8 (pin `OPENFDD_IMAGE_TAG` — avoid `:latest` on field benches)
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

Full reference: [site lifecycle](https://bbartling.github.io/open-fdd/quick-start/site-lifecycle.html).

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

<details>
<summary><strong>Field bench: required workspace/data.env.local keys</strong></summary>

Copy `workspace/bench/data.env.local.example` → `workspace/data.env.local` on OT benches. Never commit filled secrets.

| Key | Required for | Notes |
|-----|----------------|-------|
| `OPENFDD_MODBUS_HOST` / `PORT` | Modbus live gate | Set `OPENFDD_MODBUS_MODE=live` |
| `OPENFDD_BACNET_SERVER_ENABLED=0` | BACnet Who-Is on commission :9091 | Bench uses host-network commission |
| `OPENFDD_JSON_API_ENABLED=1` | JSON API driver | Also set `OPENFDD_JSON_API_URL` (bridge seeds endpoints on 3.2.4+) |
| `OPENFDD_HAYSTACK_USER` | Haystack Niagara | HTTP **Basic** auth — not SCRAM |
| `OPENFDD_HAYSTACK_PASS` | Haystack strict gate | Niagara password; restart bridge after set |

After editing: `./scripts/openfdd_bench_safe_restart.sh` then `OPENFDD_DRIVERS_VALIDATE_STRICT=1 ./scripts/openfdd_drivers_validate.sh`.

See [operations troubleshooting](https://bbartling.github.io/open-fdd/operations/troubleshooting.html) and driver docs on the site.

</details>

<details>
<summary><strong>Optional: MCP for external agents (after edge update)</strong></summary>

`openfdd_rust_site_update.sh` pulls the **core edge stack only**. MCP is opt-in.

The **`openfdd-mcp` binary ships inside `openfdd-edge-rust`** (same Cargo workspace). Use either image:

- **Full edge:** `ghcr.io/bbartling/openfdd-edge-rust:<tag>` with `--entrypoint openfdd-mcp` for stdio MCP
- **Slim MCP-only:** `ghcr.io/bbartling/openfdd-mcp:<tag>` (stdio entrypoint baked in)

**1. Edge must be healthy** (`curl -fsS http://127.0.0.1:8080/api/health`).

**2. Pull** (optional):

```bash
cd ~/open-fdd
export OPENFDD_COMPOSE_ROOT="$PWD"
export OPENFDD_IMAGE_TAG=latest

docker compose -f docker/compose.edge.rust.yml --profile mcp-sidecar pull openfdd-mcp
```

**3. Obtain an integrator JWT** (do not log or commit the token):

```bash
source scripts/openfdd_auth_lib.sh
INTEGRATOR_PW="$(openfdd_auth_plaintext_password workspace/auth.env.local integrator)"
export OPENFDD_MCP_TOKEN="$(
  curl -s -X POST http://127.0.0.1:8080/api/auth/login \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token'
)"
```

**4. Connect Cursor** — add to Cursor MCP settings (WSL path to `docker`):

```json
{
  "mcpServers": {
    "openfdd": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm", "--network", "host",
        "--entrypoint", "openfdd-mcp",
        "-e", "OPENFDD_API_BASE=http://127.0.0.1:8080",
        "-e", "OPENFDD_COMMISSION_BASE=http://127.0.0.1:9091",
        "-e", "OPENFDD_MCP_TOKEN",
        "ghcr.io/bbartling/openfdd-edge-rust:3.2.6"
      ],
      "env": {
        "OPENFDD_MCP_TOKEN": "<paste JWT from step 3>"
      }
    }
  }
}
```

**Smoke test** (stdio; Ctrl+D to exit):

```bash
docker run -i --rm --network host --entrypoint openfdd-mcp \
  -e OPENFDD_API_BASE=http://127.0.0.1:8080 \
  -e OPENFDD_MCP_TOKEN="$OPENFDD_MCP_TOKEN" \
  ghcr.io/bbartling/openfdd-edge-rust:${OPENFDD_IMAGE_TAG:-latest}
```

MCP uses **stdio JSON-RPC** — it is not an HTTP service on a port. Full tool list and bench topology: [mcp/README.md](mcp/README.md).

</details>

---

## Develop (Rust)

Tested on Windows Subsystem for Linux (WSL)

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
cp .env.example .env

# GHCR bridge (recommended — no local Rust/npm in Docker):
./scripts/openfdd_local_up.sh
./scripts/openfdd_ui_dev.sh              # Vite :5173, API proxied to :8080

# Native edge (WSL / Linux):
cargo test --workspace
cargo build --release -p open_fdd_edge_prototype
OPENFDD_WORKSPACE=$PWD/workspace ./target/release/open_fdd_edge_prototype
```

Avoid `docker compose up --build` on small hosts — it compiles Rust + npm in Docker and can OOM. Use `openfdd_local_up.sh` or GHCR images instead.

Production-style local stack with Caddy TLS:

```bash
docker compose -f docker-compose.prod.yml up -d
./scripts/openfdd_prod_validate.sh
```


## Releases (Rust 3.2.x)

| Channel | Image |
|---------|--------|
| **Default (early dev)** | Pin `OPENFDD_IMAGE_TAG=3.2.8` (avoid `:latest` on benches) |
| **Pinned version** | `ghcr.io/bbartling/openfdd-edge-rust:3.2.4` or `:v3.2.4` |
| **Short SHA** | `ghcr.io/bbartling/openfdd-edge-rust:sha-abc1234` |

**Publish a release** (maintainers): GitHub Actions → **Rust Release (GHCR + GitHub Release)** → version `3.2.4`. Runs CI, pushes edge + MCP images, creates tag `v3.2.4`, and opens a GitHub Release.

Python-era 3.1.x GHCR packages (`openfdd-bridge`, `openfdd-commission`, `openfdd-mcp-rag`, `openfdd-cloud-exporter`) are **archived** and no longer updated. Primary runtime: **`openfdd-edge-rust`** (includes `openfdd-mcp` binary). Slim `openfdd-mcp` image is transitional.

Open-FDD is for **LAN / VPN / OT networks**, not public internet hosting.


## License

MIT — see [LICENSE](LICENSE).

Version: **3.2.8**
