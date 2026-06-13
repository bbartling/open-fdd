# RCx Central overnight patch-cycle (agent runbook)

Mission: validate **OpenFDD RCx Central** against local services and (optionally) live **ACME Edge** read-only, up to **10 patch cycles** with **2-hour** spacing.

## Safety (non-negotiable)

- **Read-only** on BACnet and live BAS equipment.
- Never commit secrets, `.env`, tokens, or raw building dumps.
- Merge, publish, and deploy only when `RCX_ALLOW_MERGE=1`, `RCX_ALLOW_PUBLISH=1`, or `RCX_ALLOW_DEPLOY=1` and the owner authorizes.

## One patch cycle

1. `git pull --ff-only` on `feature/rcx-central-overview-ui` (or follow-up branch).
2. `gh pr checks 298` and `gh run view <id> --log-failed` for failures.
3. Classify CodeRabbit comments: must-fix / nice-to-have / false positive.
4. Run tests: `python3 -m pytest tests/portfolio tests/workspace_bridge -q`.
5. Start RCx Central: `./scripts/run_central_api.sh`, `./scripts/run_portfolio_dash.sh`.
6. Run `python3 scripts/rcx_central_overnight_patch_cycle.py` (try-out or overnight env).
7. Patch bugs, commit, push, confirm CI green.
8. Write `reports/rcx_central_overnight_logs/cycle_NN.md`.

## GH Actions

```bash
gh pr checks 298
gh run list --branch feature/rcx-central-overview-ui --limit 10
gh run view <RUN_ID> --log-failed
```

Fix order: unit tests → operator-bridge → docs → Docker supervisor.

## RCx Central local

```bash
./scripts/run_central_api.sh          # :8060
OPENFDD_CENTRAL_API_URL=http://127.0.0.1:8060 ./scripts/run_portfolio_dash.sh  # :8050
curl -s http://127.0.0.1:8060/health
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8050/
```

Edge connections: save URL + credentials on **Edge Connections** tab (local `portfolio/config/`).

## Live ACME (gated)

```bash
export OPENFDD_LIVE_ACME=1
export RCX_EDGE_SITE=acme
export RCX_CENTRAL_API_URL=http://127.0.0.1:8060
```

Requires ACME credentials in local registry — never log passwords.

## Try-out vs overnight

| Mode | `RCX_PATCH_CYCLES` | `RCX_CYCLE_SLEEP_MINUTES` |
|------|-------------------|---------------------------|
| Try-out | 2 | 0 |
| Overnight | 10 | 120 |

## Rev bump / deploy

Only when tests and CI pass and owner sets `RCX_ALLOW_PUBLISH=1` / `RCX_ALLOW_DEPLOY=1`. Use existing `scripts/upgrade_edge_full.sh` — do not invent new deploy paths.

## Branch cleanup after merge

```bash
git checkout master && git pull --ff-only
git branch -d feature/rcx-central-overview-ui
git push origin --delete feature/rcx-central-overview-ui
```
