---
title: Local hosting (single host)
parent: Operations
nav_order: 4
nav_exclude: true

---

# Local hosting — single-host stack

**Hosting is the local single-host stack only.** Railway and any cloud web-app
hosting (PaaS) are retired and prohibited, like DataFusion, Parquet and dual
record writing. Older docs that mention Railway are `historical/non-executable`.
Remote access is LAN/VPN to the host; there is no public cloud web host.

## Stack

One host runs central + web + Timescale from the repo checkout, pulled from GHCR
and pinned to an immutable `sha-<7>`:

```bash
docker compose --env-file .env \
  -f docker/compose.portal.yml \
  -f docker/compose.timescale.yml \
  -f docker/compose.local.yml up -d --no-build
```

| Service | Host bind (default) | Notes |
| --- | --- | --- |
| central | `127.0.0.1:8080` | `GET /api/health` (`historian:"timescale"`, `dual_write:false`) |
| web | `127.0.0.1:3000` → container `8080` | React SPA, proxies `/api` to `central:8080` |
| timescale | `127.0.0.1:5432` | project-scoped named volume |

## `.env` (gitignored, repo root)

Copy `.env.example` → `.env` and fill values. Never commit it. Keys used by the
single-host recipe (`docker/compose.local.yml`):

- `COMPOSE_PROJECT_NAME` (e.g. `openfdd-local`) and `OPENFDD_IMAGE_TAG=sha-<7>`
- `OPENFDD_SITE_ID`, `OPENFDD_CENTRAL_BIND`, `OPENFDD_WEB_BIND`, `OPENFDD_TIMESCALE_BIND`
- `OPENFDD_JWT_SECRET`, `OPENFDD_ADMIN_PASSWORD`, `OPENFDD_AGENT_PASSWORD` (deployment-unique)
- `OPENFDD_TIMESCALE_PASSWORD`, `OPENFDD_DATABASE_URL`
- NF provider: `OPENFDD_PROVIDER_SITES`, `OPENFDD_PROVIDER_POLL`, `NFURL`, `NF_CLIENT_ID`, `NF_CLIENT_SECRET`

## Re-pin to a new tip

After `Publish Open-FDD stack to GHCR` is green on the merge sha:

```bash
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web   # choose the image
./scripts/check_ghcr_tip_stack.sh sha-<7>                         # tip gate
./scripts/openfdd_local_repin.sh sha-<7> --dry-run                # preview
./scripts/openfdd_local_repin.sh sha-<7>                          # pin + pull + up + assert
```

`openfdd_local_repin.sh` edits only `OPENFDD_IMAGE_TAG` in `.env` (`--env-file`
to point elsewhere), runs `compose pull central web`, then the same
`up -d --no-build`, then the assert below. With no tag it resolves the newest
central/web by OCI `created` and refuses if they differ.

## Validate

```bash
./scripts/ops/assert_local_stack_after_repin.sh sha-<7>      # --base http://127.0.0.1:8080 default
./scripts/openfdd_health_check.sh --base http://127.0.0.1:8080
python scripts/softopen/run_softopen_local.py --building-id <id> --assert-stack
```

The assert checks health `ok`, Timescale historian, `dual_write:false`, the
health version `+<sha>`, AFDD scheduler status, the web SPA, and that the running
central/web containers use the pinned tag. Exit `0` = PASS, `2` = FAIL.

## FDD results (Timescale) and legacy manifest files

Product FDD registry runs persist to PostgreSQL (`fdd_run`, `fdd_interval_result`,
`fdd_incremental_checkpoint`). `/api/fdd/results` and readiness read those tables;
central does **not** write run-manifest JSON on the Timescale path.

Older stacks may still have files under `OPENFDD_RULE_RESULTS_DIR` or
`$OPENFDD_WORKSPACE/openfdd/rule_results/`. The product **does not** read or
delete them automatically. After you confirm Timescale rows look correct, remove
legacy manifests manually (example, adjust paths for your site id):

```bash
rm -rf "${OPENFDD_RULE_RESULTS_DIR:-$OPENFDD_WORKSPACE/openfdd/rule_results}/building=YOUR_SITE_ID"
```

Keep the Timescale volume; do not run `docker compose down -v`.

## Data safety

- Never build stack images locally; pull GHCR `sha-*` only.
- Never `docker compose down -v`, never `docker volume prune`, never set `OPENFDD_RESET_DB` on an update.
- Workspace and Timescale data live in the `<COMPOSE_PROJECT_NAME>_openfdd-workspace` / `_openfdd-timescale` volumes and survive `pull` + `up -d`.

Related: [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md) (HTTP / firewall), [ghcr-images.md](ghcr-images.md) (image/tag contract), [PATCH_CYCLE.md](PATCH_CYCLE.md).
