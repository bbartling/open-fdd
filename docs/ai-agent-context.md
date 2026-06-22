# AI agent context (Rust edge)

## Runtime

100% Rust edge — no Python/FastAPI required for install, auth, drivers, or FDD.

## AI assistance map

| Task | Guide |
| --- | --- |
| Haystack modeling + assignments | [ai-agent/haystack-and-assignments.md](ai-agent/haystack-and-assignments.md) |
| SQL HVAC fault rules | [rule-cookbook/sql-hvac-fdd.md](rule-cookbook/sql-hvac-fdd.md) |
| FDD Wires graph | [verification/fdd-wires.md](verification/fdd-wires.md) |
| Bench 5007 long validation | [verification/bench-5007-long-smoke.md](verification/bench-5007-long-smoke.md) |
| Full agent index | [ai-agent/README.md](ai-agent/README.md) |

## Safe scripts

```bash
scripts/openfdd_rust_edge_bootstrap.sh
scripts/openfdd_rust_site_backup.sh
scripts/openfdd_rust_site_update.sh
scripts/openfdd_rust_edge_validate.sh
scripts/openfdd_rust_check_ghcr_platform.sh
scripts/bench_5007_long_smoke.sh      # 6h device 5007 + FDD capture
scripts/openfdd_prod_validate.sh      # Caddy TLS + auth
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
GET  /api/model/haystack
GET  /api/model/assignments
POST /api/fdd-wires/propose-assignments
POST /api/fdd-rules/builder-sql
POST /api/fdd-rules/{id}/test-sql
GET  /api/agent/tools
```

## GHCR publish prompt

Run `cargo fmt`, `cargo test`, `docker build`, push via `.github/workflows/rust-ghcr.yml`, verify multi-arch digest, update README install URL, open PR against `master`.
