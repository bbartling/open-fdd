---
name: openfdd-railway-cli
description: >-
  Use when installing, authenticating, linking, or re-pinning the Open-FDD
  Railway lab (central and web, Timescale) via the Railway CLI. Triggers on:
  railway CLI, RAILWAY_TOKEN, railway login, railway link, railway redeploy,
  Railway re-pin, OPENFDD_NGINX_RESOLVER, sha tip on Railway, gleaming-cooperation.
---

# Railway CLI (Open-FDD hub)

`architecture_epoch: portal-timescale-v1`.

Full ops: [`docs/operations/RAILWAY_DEPLOYMENT.md`](../../../docs/operations/RAILWAY_DEPLOYMENT.md)
Checklist: [`RAILWAY_DEPLOYMENT_CHECKLIST.md`](../../../docs/operations/RAILWAY_DEPLOYMENT_CHECKLIST.md)

**Not Open-FDD MCP.** Railway CLI manages the cloud deploy. HVAC FDD tools stay in [`mcp/`](../../../mcp/) (`openfdd-mcp` plus an agent JWT to private central).

This skill does not record an FQ ops pin. Resolve the image with `./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web` after the publish job is green. `:nightly` is a channel pointer, not proof of tip. Retired 3.5.x pins and the mqtt re-pin order are `historical/non-executable` in [`docs/archive/ai-agent/historical-3.5-ot-ops.md`](../../../docs/archive/ai-agent/historical-3.5-ot-ops.md).

## Lab project

| Item | Value |
| --- | --- |
| Package | `@railway/cli` (`npm i -g @railway/cli`) |
| Auth | `railway login`. A stale `RAILWAY_TOKEN` breaks the CLI — `env -u RAILWAY_TOKEN` when the browser session is the one you want. |
| Link | project `gleaming-cooperation`, environment `production` |
| Product services | central and web. Confirm the live central service name with `railway service list`. Do not assume it is exactly `openfdd-central`. |
| Database | Timescale, attached to central. It is not an `openfdd-mqtt` service. |
| Local lab | `./scripts/openfdd_stack_up.sh portal` (HTTP behind a firewall) |

Do not re-pin `openfdd-mqtt` or `openfdd-fieldbus`. Do not set `OPENFDD_PARQUET_ROOT`.

## Tooling map

| Need | Tool |
| --- | --- |
| Publish images | GitHub Actions `Publish Open-FDD stack to GHCR` |
| Choose the sha | `./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web` |
| Tip gate | `./scripts/check_ghcr_tip_stack.sh sha-<7>` |
| Backup + re-pin | This skill |
| FDD for an agent | `openfdd-mcp` + agent JWT |
| Local portal | `./scripts/openfdd_stack_up.sh portal` |

## Agent workflow

```bash
command -v railway || npm i -g @railway/cli
railway --version
railway whoami || railway login

cd ~/open-fdd
railway status >/dev/null 2>&1 || railway link

# Newest published central and web by OCI created. Not :nightly, not a 3.5.x pin.
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web
SHA=sha-<7>

./scripts/railway_central_workspace_backup.sh

CENTRAL_SVC=openfdd-central-cQ-F   # confirm with railway service list
railway service source connect --service "$CENTRAL_SVC" \
  --image "ghcr.io/bbartling/openfdd-central:${SHA}"
# Wait until GET /api/health on that service is 200, then web.
railway variable set OPENFDD_NGINX_RESOLVER=auto --service openfdd-web
railway service source connect --service openfdd-web \
  --image "ghcr.io/bbartling/openfdd-web:${SHA}"
```

Smoke is `GET /api/health` (lean readiness). With auth on, `/api/tenants` needs a bearer token. The health version must match the pinned sha. Deploy order is Timescale (already attached), central healthy, then web.

Re-pin is an image tag change. Do not delete the central `/workspace` volume. Docs: [`backup-update-restore.md`](../../../docs/operations/backup-update-restore.md).

Disposable portal qualification is a separate owned stack. Do not point a scanner at the public Railway URL from this skill.

## Non-negotiables

- Never commit `RAILWAY_TOKEN`, JWTs, or Railway variable dumps.
- Never log `railway variable list --json`.
- Do not hard-code `--service openfdd-central` when `railway service list` shows another name.
- Do not re-pin web before central is healthy.
- Do not re-pin central without the workspace backup.
- Do not deploy fieldbus on Railway.
- Railway CLI is not `openfdd-mcp`.

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-stack-ghcr`](../openfdd-stack-ghcr/SKILL.md) — local GHCR recreate
- [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md) — empty charts are missing roles
