# Archive: Open-FDD central (4.x)

Code under this tree is **archived and unmaintained**. It is the pre-plugin Open-FDD 4.0 stack: the Rust `openfdd-central`
service, its own Timescale ingest of NF data, the portal/stack docker compose files and the GHCR image workflows.

Why: [ADR-014](../../docs/architecture/adr-014-open-fdd-as-nf-plugin.md) moved Open-FDD into Normal Framework as one NF
app (`nf-app/`). NF already owns polling, the model, history, auth, remote access and (full profile) the TimescaleDB
historian, so a second historian/model/auth stack is retired. Map with evidence per item:
[`docs/migration/nf-plugin/ARCHIVE_MAP.md`](../../docs/migration/nf-plugin/ARCHIVE_MAP.md).

- Release pin: git tag **`v4.0.11-central`** (last commit before the plugin work; full working tree).
- Not a Cargo workspace member, not built or tested by GitHub Actions, not published to GHCR. The files were moved with
  plain `mv`; relative paths are preserved.

## What is here and what replaced it

| Archived path | What it was | Replaced by |
| --- | --- | --- |
| `services/central` | Rust service: NF ingest (REST/gRPC), Timescale historian, SQL FDD runner, REST + JWT, static UI | `nf-app/` (UI + hooks), NF's own API/auth/history; SQL pack runs in NF's TimescaleDB (full profile) |
| `edge`, `crates/fdd_store`, `crates/fdd_resources` | Library code used only by central (auth, CSV ingest, AFDD scheduler, admission control) | NF hooks (`nf-app/hooks/`) |
| `crates/nf_grpc`, `crates/openfdd_contracts` | NF gRPC client, REST/OpenAPI contracts | NF HTTP/JSON API from the app (`nf-app/static/nf.js`) |
| `mcp`, `Dockerfile.mcp` | stdio MCP proxy for central's JWT REST | NF's own MCP server |
| `docker/` | portal / csv / react / timescale / caddy / qual compose files | NF compose + `deploy/nf-caddy/` (front door), `docs/install/nf-plugin.md` |
| `deploy/caddy` | standalone HTTPS Caddyfiles for central | `deploy/nf-caddy/` |
| `frontend`, `config/nf` | UI pointer README, central NF provider credentials example | NF auth / portal |
| `scripts/` (stack, ghcr, gates, security, qualification portal+zap, release smoke, CI browser guards) | Operate and verify the central stack | `scripts/nf/` (`nf_app_sync.py`, rule catalog), `nf-app-ci.yml` |
| `tests/security`, `tests/qualification` (portal/ZAP), `tests/operations` | Stack security/qualification tests | n/a |
| `.github-workflows/` | `rust-ci`, GHCR stack/MCP publish, release, prune, tip checks, central crate tests | `nf-app-ci.yml`, `sql-pack-ci.yml` (outside `archive/`) |

Kept in the repo root because the plugin and the PyPI package use them: `sql/` (rule pack, schema), `open_fdd/`,
`crates/fdd_core`, `fdd_rules`, `fdd_tsdb` (SQL/DB bootstrap and registry validation), `fdd_csv` (undecided).

## Restore

Whole old product: `git checkout v4.0.11-central` (works in a separate worktree: `git worktree add ../open-fdd-central v4.0.11-central`).

Piecemeal from this tree:

1. Move the directories back to their original relative paths (`archive/central-v4/services` -> `services`, `edge`, `mcp`,
   `docker`, `frontend`, `deploy/caddy`, `config/nf`, `Dockerfile.mcp`, `crates/{nf_grpc,openfdd_contracts,fdd_store,fdd_resources}`,
   and the matching `scripts/` and `tests/` subtrees).
2. Re-add the workspace members to the root `Cargo.toml`: `edge`, `mcp`, `crates/fdd_store`, `crates/fdd_resources`,
   `crates/openfdd_contracts`, `crates/nf_grpc`, `services/central`.
3. Move the files in `.github-workflows/` back to `.github/workflows/` and restore the edits made to `fdd-engine-ci.yml`,
   `pypi-sql-parity.yml`, `c3c-sqlqual-11-12a.yml`, `si-parity.yml`, `security.yml`, `appsec.yml` from git history
   (`git log -- .github/workflows/<file>`).
4. Do not point central at an NF-owned TimescaleDB; it expects its own `sample` table and schema.
