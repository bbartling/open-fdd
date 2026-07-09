# Branch reconciliation — Stage 4 (2026-07-09)

Audit performed before any new Stage 4 parity/tuning code.

## Default / public branch

| check | result |
| --- | --- |
| `git remote show origin` HEAD branch | **develop** |
| `git symbolic-ref refs/remotes/origin/HEAD` | `refs/remotes/origin/develop` |
| GitHub default | **develop** (not `master`) |

**Source of truth:** `develop` @ `b93a929`

## Audit commands run

```text
git status          → clean, on develop, up to date with origin/develop
git branch          → * develop
git branch -a       → develop, remotes/origin/HEAD → origin/develop, remotes/origin/develop
git fetch --all --prune → no stale remote refs
git branch -vv      → develop b93a929 [origin/develop]
```

## Branch inventory

| branch | local/remote | latest hash | latest message | ahead/behind origin | merged into develop | unique work | action | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **develop** | both | `b93a929` | Stage 4a: ECON-4 confirm CTE, OAT-METEO LEFT JOIN, parity plan | 0/0 | yes (tip) | **all Stage 2–4 work** | **keep — source of truth** | Only active branch |
| ~~stage3-datafusion-parity-building100~~ | deleted | was `b93a929` | (same as develop) | n/a | yes (fast-forward) | none | **delete later → deleted** | Merged to develop 2026-07-09; remote deleted |
| ~~master~~ | deleted | was `b93a929` | (duplicate of develop) | n/a | yes (same tip) | none | **delete later → deleted** | Created by mistake; removed; develop is canonical |

## No stranded branches

After `git fetch --all --prune`:

- **0** local branches besides `develop`
- **0** remote branches besides `origin/develop`
- **0** unpushed local commits on `develop`
- **0** remote commits not in local `develop`

## Work content on `develop` (commit range `bdb8881..b93a929`)

| area | commits | key paths |
| --- | --- | --- |
| Stage 2 parity | `bdb8881` | `rust_fdd_core/`, `sql_rules/`, compare report |
| Stage 3 VAV_7 + SQL tuning | `e3baa8a` | `role_rank.rs`, `cookbook_engine.py`, `tuning.rs`, `sql_rules_registry.py`, `dashboard_sql_tuning.js`, `/api/sql-rules*` |
| Stage 4a plan + SQL | `b93a929` | `econ4_low_oa_frac.sql`, `oat_meteo_fault.sql`, `STAGE4_PARITY_REMAINING_PLAN.md`, benchmark refresh |

### Files touched (Stage 3 + 4a, `e3baa8a` + `b93a929`)

- **Rust:** `rust_fdd_core/crates/fdd_core/src/role_rank.rs`, `columns.rs`, `fdd_rules/tuning.rs`, `registry.rs`, `runner.rs`, `fdd_store/ingest.rs`
- **SQL:** `sql_rules/registry.yaml`, `*.sql` (VAV-1, FC13, OAT-METEO, ECON-4, zone rollups)
- **Python:** `fdd_app/backend/cookbook_engine.py`, `sql_rules_registry.py`, `app.py`
- **Frontend:** `fdd_app/frontend/static/dashboard_sql_tuning.js`, `dashboard.css`
- **Tuning:** `rule_tuning/defaults.yaml`
- **Docs:** `vibe19_agent_spec/benchmarks/`, `SESSION_LOG.md`, `BUILD_CHECKPOINTS.md`, API/tuning/React plan docs

## Merge / cherry-pick log

| source | target | method | result |
| --- | --- | --- | --- |
| `stage3-datafusion-parity-building100` | `develop` | fast-forward | ✅ all commits preserved |
| `stage3-datafusion-parity-building100` | (remote) | deleted after merge | no unique commits |
| `master` | n/a | deleted (duplicate tip) | no unique commits |

**No cherry-picks required** — all agent work already on `develop`.

## Working branch for Stage 4 continuation

```bash
git checkout develop
git pull --ff-only origin develop
git checkout -b stage4-finish-parity-and-tuning
```

## Branches safe to delete (already done)

- `stage3-datafusion-parity-building100` — merged, identical tip
- `master` — duplicate of develop, not the GitHub default

## Branches to investigate

_None — audit clean._

## Conflict policy (for future merges)

Preserve: Stage 4 benchmark logic, SQL registry, tuning API, dashboard SQL panel, Python oracle, weather staging, VAV_7 role ranking, Rust tests, pandas dashboard behavior.

## Baseline rerun (2026-07-09, branch `stage4-finish-parity-and-tuning` @ `b93a929`)

| metric | value |
| --- | ---: |
| rules compared | 19 |
| SQL rules succeeded | 19/19 |
| pass | **314** |
| fail | **54** |
| skipped | **11** |
| max abs Δ | **32.733h** (OAT-METEO / AHU_2) |
| compare exit code | 1 (material_failure expected) |

Matches prior Stage 4a public baseline. VAV_7 fixed; zone analytics proven.

### Test suite (this machine)

| suite | result |
| --- | --- |
| `validate_data.py` | GO |
| Rust fmt/clippy/tests | clean; **22** tests passed |
| `pytest -q` | **104 errors** — `PermissionError` on Windows (env/AV lock), not code regression; re-run locally |
| Dashboard smoke | not run this checkpoint |

## Post-reconciliation checkpoint

- Branch: `stage4-finish-parity-and-tuning` from `develop` @ `b93a929`
- Commit: see git log after reconciliation checkpoint commit
