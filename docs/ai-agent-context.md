# AI agent context (Rust edge)

## Runtime

100% Rust edge — install and operate via Docker/GHCR, not PyPI.

## AI assistance map

| Task | Guide |
| --- | --- |
| Haystack modeling + assignments | [ai-agent/haystack-and-assignments.md](ai-agent/haystack-and-assignments.md) |
| SQL HVAC fault rules | [rule-cookbook/sql-hvac-fdd.md](rule-cookbook/sql-hvac-fdd.md) |
| FDD Wires graph | [verification/fdd-wires.md](verification/fdd-wires.md) |
| Live FDD validation (dev) | [testing/live-fdd-validation.md](testing/live-fdd-validation.md) |
| Full agent index | [ai-agent/README.md](ai-agent/README.md) |

## Safe scripts

```bash
scripts/openfdd_rust_edge_bootstrap.sh
scripts/openfdd_rust_site_backup.sh
scripts/openfdd_rust_site_update.sh
scripts/openfdd_rust_edge_validate.sh
scripts/openfdd_rust_check_ghcr_platform.sh
scripts/openfdd_inspection_build.sh      # local UI inspection build
scripts/openfdd_prod_validate.sh         # Caddy TLS + auth
```

## Never

- delete `workspace/`
- `docker compose down -v`
- `docker volume prune`
- print `auth.env.local`, `bootstrap_credentials.once.txt`, or JWT tokens
- BACnet/Modbus write without explicit human approval + audit
- `pip install open-fdd` or any Python runtime install path

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

## GHCR publish (maintainers)

Run `cargo fmt`, `cargo test`, dashboard `npm run build`, then merge to `master` or tag a release.
Publishing runs via `.github/workflows/rust-ghcr.yml` — wait for GitHub Actions green before merge.
Docs-only PRs do not require manually pushing a new image tag.
