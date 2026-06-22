# AI agent context (Rust edge)

## Runtime

100% Rust edge — no Python/FastAPI required for install, auth, drivers, or FDD.

## Safe scripts

```bash
scripts/openfdd_rust_edge_bootstrap.sh
scripts/openfdd_rust_site_backup.sh
scripts/openfdd_rust_site_update.sh
scripts/openfdd_rust_edge_validate.sh
scripts/openfdd_rust_check_ghcr_platform.sh
```

## Never

- delete `workspace/`
- `docker compose down -v`
- `docker volume prune`
- print `auth.env.local` or JWT tokens
- BACnet/Modbus write without explicit human approval + audit

## API entry points

```text
GET  /api/health
POST /api/auth/login
GET  /api/health/stack
GET  /api/bacnet/driver/tree
GET  /api/agent/tools
POST /api/rules/batch
```

## GHCR publish prompt

Run `cargo fmt`, `cargo test`, `docker build`, push via `.github/workflows/rust-ghcr.yml`, verify multi-arch digest, update README install URL, open PR against `rust-rewrite-1`.
