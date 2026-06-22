# Open-FDD Rust Edge

<p align="center">
  <a href="https://discord.gg/Ta48yQF8fC"><img src="https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/bbartling/open-fdd/actions/workflows/rust-ci.yml"><img src="https://github.com/bbartling/open-fdd/actions/workflows/rust-ci.yml/badge.svg?branch=rust-rewrite-1" alt="Rust CI"></a>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT">
  <img src="https://img.shields.io/badge/status-Rust%20Edge-blue" alt="Rust Edge">
  <img src="https://img.shields.io/badge/Rust-1.93-orange?logo=rust" alt="Rust">
  <img src="https://img.shields.io/badge/Apache%20Arrow-53-blue" alt="Arrow">
  <img src="https://img.shields.io/badge/DataFusion-SQL-purple" alt="DataFusion">
  <img src="https://img.shields.io/badge/GHCR-openfdd--edge--rust-blue?logo=docker" alt="GHCR">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/bbartling/open-fdd/master/image.png" alt="Open-FDD logo" width="440">
</p>

<p align="center">
  Local-first, on-prem, vendor-neutral HVAC supervisory fault detection — <strong>100% Rust edge runtime</strong>:
  Rust API, React UI, Apache Arrow historian, DataFusion SQL FDD, JWT auth, BACnet/Modbus/Haystack drivers, Docker/GHCR lifecycle.
</p>

<p align="center">
  <a href="docs/README.md"><img src="https://img.shields.io/badge/Documentation-read_online-2563EB?style=for-the-badge" alt="Documentation"></a>
  <a href="docs/quick-start/rust-edge-bootstrap.md"><img src="https://img.shields.io/badge/Quick%20Start-Rust%20Edge-059669?style=for-the-badge" alt="Rust quick start"></a>
</p>

---

## GHCR install (production edge)

Primary Rust image:

```text
ghcr.io/bbartling/openfdd-edge-rust:latest
```

Legacy Python stack (compatibility only — not the Rust edge path):

```text
ghcr.io/bbartling/openfdd-bridge
ghcr.io/bbartling/openfdd-commission
ghcr.io/bbartling/openfdd-mcp-rag
```

### Fresh install

```bash
curl -fsSL -o /tmp/openfdd_rust_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/rust-rewrite-1/scripts/openfdd_rust_edge_bootstrap.sh
bash /tmp/openfdd_rust_edge_bootstrap.sh --start
```

Open `http://127.0.0.1:8080` — sign in with integrator credentials from `~/open-fdd/workspace/auth.env.local` (password never printed by bootstrap).

### Update existing site

```bash
cd ~/open-fdd
./scripts/openfdd_rust_site_backup.sh
./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_edge_validate.sh
```

**Never** run `docker compose down -v`. **Never** delete `workspace/`.

---

## Developer / source checkout

```bash
cp .env.example .env
docker compose up --build
# or
cargo test --workspace
cargo run -p open_fdd_edge_prototype
```

---

## Architecture

| Component | Technology |
| --- | --- |
| API + auth | Rust (`edge/`) |
| UI | React static assets |
| Historian | Apache Arrow RecordBatches |
| FDD | DataFusion SQL + confirmation duration |
| BACnet | rusty-bacnet (live) or simulated |
| Modbus | Native Rust TCP client |
| Publish | GHCR multi-arch (`rust-ghcr.yml`) |

---

## Security

- Generated `workspace/auth.env.local` — operator / integrator / agent users
- `chmod 600` where possible; secrets never printed in bootstrap/update logs
- Bind API to LAN / Tailscale / reverse proxy — not public internet
- BACnet writes require integrator + explicit human approval workflow

See [docs/security/rust-edge-auth.md](docs/security/rust-edge-auth.md).

---

## AI agent prompts

### Fresh Rust edge bootstrap

```text
Install Docker if missing. Detect linux/amd64 or linux/arm64. Run openfdd_rust_edge_bootstrap.sh --start from rust-rewrite-1. Validate /api/health and login. Do not print secrets. Do not expose port 8080 to the public internet. Never docker compose down -v. Never delete workspace/.
```

### Operator session

```text
Login as integrator from workspace/auth.env.local. Call GET /api/health/stack, GET /api/bacnet/driver/tree, GET /api/rules. Run safe diagnostics only. No BACnet/Modbus writes without explicit human approval. Do not paste tokens or passwords into chat.
```

### Backup / update / restore

```text
Run openfdd_rust_site_backup.sh, then openfdd_rust_site_update.sh with NEW_TAG if needed. Validate with openfdd_rust_edge_validate.sh. Keep backup on failure. Restore workspace only when asked. Never volume prune. Never compose down -v.
```

Full guide: [AGENTS.md](AGENTS.md) and [docs/ai-agent-context.md](docs/ai-agent-context.md).

---

## Legacy scripts (Python-era)

These remain for local dev checkout but are **not** the primary Rust GHCR install path:

```text
scripts/openfdd_edge_bootstrap.sh   → use openfdd_rust_edge_bootstrap.sh
scripts/openfdd_site_update.sh      → use openfdd_rust_site_update.sh
scripts/openfdd_check_ghcr_platform.sh → use openfdd_rust_check_ghcr_platform.sh
```

---

## Docs

- [Rust edge bootstrap](docs/quick-start/rust-edge-bootstrap.md)
- [Site lifecycle](docs/quick-start/rust-site-lifecycle.md)
- [Raspberry Pi / ARM64](docs/quick-start/raspberry-pi-rust-edge.md)
- [Update & restore](docs/operations/rust-update-restore.md)
- [Unpushed work log](UNPUSHED_WORK.md)

Version: **3.2.0** (`VERSION`)
