---
name: openfdd-stack-ghcr
description: >-
  Use when pulling or verifying Open-FDD GHCR stack images for the portal
  recipe (central, web, Timescale). Triggers on: nightly, openfdd-central,
  openfdd-web, GHCR, openfdd_stack_up, OPENFDD_IMAGE_TAG, re-pin, local stack.
---

# Stack GHCR

`architecture_epoch: portal-timescale-v1`.

Full protocol: [`CONTAINER_AGENT.md`](../../CONTAINER_AGENT.md).

`nightly` is a channel pointer. Run the image you resolved:

```bash
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web
```

Pin `OPENFDD_IMAGE_TAG` to that `sha-*`. Do not treat a tag named `nightly` as proof of tip.

**Unmerged `frontend/web` is local web only.** Do not serve `ghcr.io/bbartling/openfdd-web:sha-*` for an unmerged UI. `./scripts/openfdd_demo_gate.sh` must exit 0 before a login URL.

Product central image is Rust/debian only (no Python). Ingest is the Normal Framework portal API and CSV.

## Recipes

| Recipe | What it is |
| --- | --- |
| `portal` | 4.0 default: central + web + Timescale. `./scripts/openfdd_stack_up.sh portal` |
| `csv` | central + web, no portal provider env forwarder |

`openfdd_stack_up.sh` refuses `standalone`, `edge`, and `react-ot`. Those fieldbus recipes are `historical/non-executable` ([`docs/archive/ai-agent/historical-3.5-ot-ops.md`](../../../docs/archive/ai-agent/historical-3.5-ot-ops.md)). The archive render does not start containers:

```bash
OPENFDD_OT_ARCHIVE_RESTORE=1 ./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay
```

Do not pull `openfdd-fieldbus` or `openfdd-mqtt` as the product stack.

## Local single-host stack and re-pin

Hosting is the local single-host stack only. Railway and any cloud web-app hosting are retired and prohibited (like DataFusion, Parquet and dual record writing); old Railway notes are `historical/non-executable`.

The stack runs from the repo checkout with secrets and the pin in the gitignored repo-root `.env`:

```bash
docker compose --env-file .env -f docker/compose.portal.yml \
  -f docker/compose.timescale.yml -f docker/compose.local.yml up -d --no-build
```

Re-pin to a published tip (edits only `OPENFDD_IMAGE_TAG` in `.env`, pulls central/web, `up -d --no-build`, then asserts):

```bash
./scripts/check_ghcr_tip_stack.sh sha-<7>
./scripts/openfdd_local_repin.sh sha-<7>            # --dry-run to preview; no tag = newest-by-created
./scripts/ops/assert_local_stack_after_repin.sh sha-<7>   # base defaults to http://127.0.0.1:8080
```

The assert checks `/api/health` (`historian:"timescale"`, `dual_write:false`, version `+<sha>`), AFDD scheduler status, the web SPA on `:3000`, and the running central/web image tags. Never build images locally, never `down -v`, never prune volumes; workspace and Timescale data stay in the project-scoped named volumes. Runbook: [`docs/operations/LOCAL_HOSTING.md`](../../../docs/operations/LOCAL_HOSTING.md).

Set `OPENFDD_AGENT_PASSWORD` on central for MCP (username `agent`). Do not put `OPENFDD_ADMIN_PASSWORD` in an MCP config. Admins may `POST /api/auth/agent-token` for a short-lived operator JWT.

Local Compose is plain HTTP (`:3000` / `:8080`) behind a firewall. Handbook: [`docs/operations/LOCAL_DEPLOYMENT.md`](../../../docs/operations/LOCAL_DEPLOYMENT.md).

Low-RAM hosts do not `docker build` stack images. Prune, then `./scripts/openfdd_stack_pull.sh portal` and `./scripts/openfdd_stack_up.sh portal --no-pull`.

Hourly CSV append is `POST /api/csv/import/package/append` on central.

After publish, poll with `./scripts/ghcr_watch_central.py`.

Workflow: `ghcr-openfdd-stack.yml` (retargets nightly on master). MCP: `rust-ghcr-mcp.yml`.

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-architecture`](../openfdd-architecture/SKILL.md) — engine boundary
