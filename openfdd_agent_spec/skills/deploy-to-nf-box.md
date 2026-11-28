---
name: deploy-to-nf-box
description: Deploy the Open-FDD full app or Lite to an NF box with nf_app_sync.py or the NF MCP.
---
# Deploy to an NF box

Need NF 3.10 or newer and a console login. Keep the env file outside git (`NF_CONSOLE_URL`, `CONSOLE_USERNAME`, `CONSOLE_PASSWORD`).

1. Run the tests first: `node --test nf-app/tests/*.test.mjs lite/tests/*.test.mjs`.
2. Choose the edition. **1 GB boxes (Raspberry Pi 3) get Lite only** (`lite/app.json`). Full (`nf-app/app.json`) runs
   server-side Node DuckDB (`@duckdb/node-api` `2.0.1-r.1`, Parquet on disk) or Timescale. `auto` uses Timescale on
   the Timescale build or when that option is set, otherwise DuckDB. If `@duckdb/node-api` cannot load, the run fails.
   `duckdb>=2.0.1` is the Python parity pin only. Both editions answer SPARQL with the `oxigraph` npm package.
3. `python3 scripts/nf/hooks/nf_app_sync.py --env <env file> diff nf-app/app.json` then
   `... push nf-app/app.json` (`--skip-hooks` for UI only, `--hook fdd` for one hook; `run ... --hook fdd` runs it now).
   Alternative: NF MCP `manage_app` (create, `write_file`, `restart`) and `deploy_hook`; run a hook with its uuid.
4. Verify: page loads at `/api/v1/apps/static/open-fdd/` (or `open-fdd-lite`), no console errors, live values, hooks ran.

Rules: never run builds, npm installs or tests on a small box; never write BACnet to field devices without the
owner's approval; static files are cached 5 minutes (use `?v=N`); `application.id` must equal the slug of `application.name`.
After NF login is enabled the manifest needs `auth.apiKey.scopes`. See `docs/install.md`.

Installing, upgrading, removing an old version or debugging a 401: use the `install-upgrade-troubleshoot` skill (run `doctor` first).

Before touching a live box read `nf-gotchas.md` (this folder). Related runbooks in `docs/operations/nf/`: `lite-vs-full.md`,
`front-door-caddy.md` (Caddy; set `APP_ID=open-fdd-lite` on a Lite box so the bare URL opens Lite),
`nf-upgrade-compose.md`, `bacnet-validate.md` (see the `bacnet-validate` skill). Read-only checks of a deployed box:
`scripts/nf/tools/` (`nf_portal_sensors.py`, `nf_sensor_history.py`).

## Release bundles, prune, host health

Each `vX.Y.Z` tag runs `.github/workflows/nf-app-release.yml`. It builds `open-fdd-<version>.zip` and
`open-fdd-lite-<version>.zip` with `scripts/nf/build_app_dist.py` from the same manifests `nf_app_sync.py` pushes.
Check a tree locally with `python3 scripts/nf/build_app_dist.py --check`.

`prune-points` lists this app's orphan and long-stale result points and deletes nothing unless `--yes` is passed:

```bash
python3 scripts/nf/hooks/nf_app_sync.py --env <env file> prune-points nf-app/app.json
python3 scripts/nf/hooks/nf_app_sync.py --env <env file> prune-points nf-app/app.json --stale-days 30 --yes
```

`doctor` prints host memory, disk and service restarts (`host_health` in `scripts/nf/hooks/nf_app_sync.py`). Those
lines are PASS, WARN or SKIP. They do not fail `doctor`.

## Timescale schema gate

`push` and `install` read the installed Timescale schema first (read-only) and stop before any write when the database
is older than the release needs, or the check cannot run (#1633). Apply `nf-app/timescale/install.sql` as the database
owner, then push. `--allow-schema-upgrade-pending` overrides it; scheduled `fdd` runs then fail until the schema is
applied. `--dry-run` is for `install` only; other actions refuse it (#1634).

## Live patching (last resort)

Do not hand-edit the box as the normal fix path. If a hotfix is required to unblock verification, follow the **Live patching a box** section in repo-root `AGENTS.md`: read-only capture first, patch one path, commit on a patch branch (HTML without `?v=` stamps), restart before verify, do not rewrite push-manifest hashes early. Coding agents do not deploy to a live console and do not delete live points. The repository owner does that after the tag exists.
