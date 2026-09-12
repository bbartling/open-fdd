# Wave M D1 � Root-cause report (durable results / release / UX)

**Date:** 2026-09-12  
**Source tip (git):** record at land time (`origin/master` tip; docs tip may advance)  
**Ops pin (Railway central image):** `ghcr.io/bbartling/openfdd-central:sha-e80237c` � health `3.5.6+e80237c0e758`  
**Volume:** `openfdd-central-cq-f-volume` ? `/workspace` (1.3?GB / 4.9?GB)  
**Storage env (non-secret):** `OPENFDD_WORKSPACE=/workspace`, `OPENFDD_PARQUET_ROOT=/workspace/openfdd`, `OPENFDD_STORAGE_URL=file:///workspace/openfdd`, `multi_tenant=false`

Leads from `ecd97a473405` revalidated against tip code (not assumed unchanged).

## Scenario matrix

| Scenario | Expected durability | Finding |
|----------|---------------------|---------|
| Same-container restart | Volume state survives | **Static OK** � Railway volume mount `/workspace` |
| New-image replace | Same volume; process counters reset | **Static OK** � pin changes image only; `ingest_ok` resets (documented) |
| Browser reload | Should show last completed results | **Partial** � Overview auto-loads analytics; FDD rule results path may miss persistent store |
| Logout/login | Same job results without rerun | **Unverified in browser this session** � blocked on D4 auto-load of rule summaries |
| Building/job switch | No cross-job flash | **Partial** � Overview clears on site change; global `openfdd.ui.rule_params` can leak tuning |
| Account/tenant switch | Isolation | **Mode OFF** � tenant switch soft; session 401 race still relevant |

## Lead revalidation

| Lead | Status | Evidence |
|------|--------|----------|
| Rule results ? `.cache/rule_results` | **REPRODUCED (static)** | [`edge/src/fdd/registry_api.rs`](../../edge/src/fdd/registry_api.rs) `results_dir` defaults to `.cache/rule_results` unless `OPENFDD_RULE_RESULTS_DIR`. Central Dockerfile `WORKDIR /app` � relative `.cache` is **not** under `/workspace` volume unless cwd/env override. |
| Backup tar openfdd+mqtt with `\|\| tar .` fallback | **REPRODUCED (static)** | [`scripts/railway_central_workspace_backup.sh`](../../scripts/railway_central_workspace_backup.sh) lines 25�27: failed first tar still writes fallback stream to same file ? concat risk. |
| Single `session_config.json` | **REPRODUCED (static)** | [`edge/src/fdd/session_config.rs`](../../edge/src/fdd/session_config.rs) � one hub-wide `workspace/data/session_config.json`. |
| Global browser rule override key | **REPRODUCED (static)** | [`frontend/web/src/lib/ruleParams.ts`](../../frontend/web/src/lib/ruleParams.ts) `RULE_PARAMS_STORAGE_KEY = "openfdd.ui.rule_params"` � not building-scoped. |
| Overview auto-load | **REPRODUCED (working)** | [`OverviewPopulated.tsx`](../../frontend/web/src/components/OverviewPopulated.tsx) auto-loads on site/visibility; Wave H demo freshness. |
| HomePage empty on failure | **REPRODUCED (static)** | [`HomePage.tsx`](../../frontend/web/src/pages/HomePage.tsx) `.catch(() => [])` on buildings/equipment ? empty inventory masks errors. |
| Stale 401 clears newer session | **PARTIAL / still open** | [`client.ts`](../../frontend/web/src/api/client.ts) skips 401 if `signal.aborted`, but **no session-generation guard** � late 401 from older request can still clear token after re-login. `apiFetchBlob` lacks abort check. |

## Authoritative vs disposable (inventory sketch)

| Item | Intended path | Notes |
|------|---------------|-------|
| Historian Parquet | `/workspace/openfdd` | Volume-backed � OK |
| MQTT certs (central copy) | `/workspace/mqtt` | Backed up; volume |
| Jobs / findings | under workspace via jobs module | Confirm in D2 |
| AFDD checkpoints | canonical state under store | Exists (`afdd_scheduler.rs`) |
| Rule results JSON | **WRONG default** `.cache/...` | D2 must move to volume |
| Browser rule params | localStorage global | D4 scope by building/job |
| Disposable DF caches | `.cache/parquet` candidates | Keep disposable |

## Unverified (need D4/D5 gates)

- End-to-end logout/login without refresh after FDD run on Railway tip.
- Backup restore-to-empty application-visible parity (gate 6).
- Image-replace sample digests (gate 5).

## Next

Wave M **D2** (persistent rule results + readiness) ? **D4** (401 session gen + scoped params + honest HomePage) ? **D5** (backup + release orchestrator) ? **D3** deepen durable run metadata for flood/auto-results.
