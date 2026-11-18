# Release 5.0.21 cycle ledger

Internal; excluded from the Pages site (`docs/_config.yml` excludes `plans/**`). Procedure:
`C:\Users\ben\Documents\prompts\2026-11-17-openfdd-issue-validation-and-closure.md`.

States: `OPEN -> OWNED -> PR READY -> INDEPENDENTLY VERIFIED -> INTEGRATED -> RELEASED -> CLOSED`.
Issues stay open after integration (READY FOR RELEASE); Grok posts closure receipts after the default-branch merge.

## Writer slot

| Field | Value |
|---|---|
| Current writer | Claude |
| Checkout | `C:\Users\ben\Documents\open-fdd` |
| Branch in checkout | see the latest checkpoint below |
| Claimed paths | `.github/workflows/**`, `plans/**`, `sql/fdd/**`, `open_fdd/rules/sensor_sweep_catalog.py`, `nf-app/hooks/lib/engines.js`, `tests/parity/**`, `open_fdd/data/units.json` |
| Handoff | Grok may triage read-only; ask in this file before taking the slot |

## Baseline (pickup 2026-11-17)

- `release/5.0.21` = `7642f407` (tracks origin). App `VERSION` and `nf-app/package.json` = 5.0.21. PyPI package = 4.5.11.
- Default branch `master` = `95266656`. Ruleset "Protect master" (default branch only): squash merges,
  required checks `Gitleaks`, `npm audit (nf-app)`, `pandas == SQL parity / pandas oracle vs SQL pack`,
  `pandas == SQL parity / pandas == SQL == SPARQL-client`, strict. `release/5.0.21` has no protection: topic PRs
  into it must show the same checks green on their head before merge (discipline, not enforcement).
- 42 open issues (list below), 1 open PR (#1664).
- Dirty files at pickup (`docs/rules/borrowing-sql.md`, `tutorials/duckdb_sql_parity/README.md`, beginner-tutorial
  links) were stashed as `tutorial-links (preserve)` and are carried on topic branch `docs/tutorial-links`.
- Pre-existing TEMP worktrees (not created by this cycle; owner's to retire): `%TEMP%\ofdd-1608`
  (`feat/run-proof-gate`, upstream gone), `%TEMP%\ofdd-1608-base`, `%TEMP%\open-fdd-ip-oracle-worktree`.
  Leave them until their branches are confirmed merged/superseded.

## CI routing (audited 2026-11-17)

| Workflow | Trigger before | Change in this cycle |
|---|---|---|
| `security.yml` (calls `parity.yml`; ZAP, npm audit, gitleaks) | every push/PR | none needed |
| `nf-app-ci.yml` | every push/PR on paths | none needed |
| `python-matrix.yml` | push master; PR any | push adds `release/**` |
| `duckdb-tutorial.yml` | push master; PR any | push adds `release/**` |
| `docs-pages.yml` | push/PR master,main | push/PR add `release/**`; deploy job now also requires `github.ref == refs/heads/master` |
| `parity-stress.yml` | schedule (master) + dispatch with `ref` input | none; dispatch with `--ref release/5.0.21 -f ref=release/5.0.21` and verify checkout SHA |
| `nf-app-release.yml`, `publish-open-fdd.yml` | tags / dispatch | none; publishing stays on final tags; use `dry_run=true` for validation |

## Issue table

Owner C = Claude, G = Grok. "Next" is the next concrete action.

| # | Owner | Scope | State | Branch / PR | Next |
|---|---|---|---|---|---|
| 1669 | C | `percent_0_100` RH alias in all helper copies + units metadata; long-form sweep vector | OWNED | `fix/1669-rh-percent-alias` | implement + regression |
| 1670 | C | SCHED-247 OFF/unknown/completeness, honest observed duration | OPEN | | read rule + repro |
| 1673 | C | SV-STALE = gap/missing; SV-FLATLINE = stuck values; dedupe silence; expected series | OPEN | | design after #1671 contract |
| 1631 | C | Run-proof coverage/denominator follow-ups | OPEN | | |
| 1635 | C (+G client) | Resolved proof into SPARQL client frames | OPEN | | |
| 1636 | C | Occupancy calendar synthesis | OPEN | | |
| 1639 | C | Expanded SI stress, seeds, replay | OPEN | | |
| 1640 | C | DataFusion parity adapter | OPEN | | |
| 1641 | C | Generic coil performance rule | OPEN | | |
| 1642 | C | Divergences + implementation-aware pins | OPEN | | |
| 1646 | C | Tuners, motor-status wording, RCx coverage | OPEN | | after #1671/#1672 |
| 1671 | C | One visible timer per rule; tuner migration | OPEN | | |
| 1672 | C | Sliders/booleans, SI validation, scoped persistence | OPEN | | after #1671 |
| 1649 | C | SQL analytics restoration + pandas parity | OPEN | | phase 2 |
| 1643 | C | Fast Overview, lazy heavy views | OPEN | | phase 3 |
| 1644 | C | Split `hooks/fdd.js` into modules | OPEN | | phase 3 |
| 1645 | C | Native DuckDB Standard, Parquet, notebook, Lite migration | OPEN | | phase 3; needs real NF targets |
| 1567 | C | NF-native install paths, non-SSH docs | OPEN | | phase 3 |
| 1614 | C | Safe prune planning | OPEN | | phase 3 |
| 1615 | C | Host health via NF API | OPEN | | phase 3 |
| 1616 | C | Canonical skills, README/badges, link drift | OPEN | | phase 3 |
| 1624 | C | Disposable real-NF CI | OPEN | | needs disposable NF |
| 1633 | C | Timescale preflight before writes | OPEN | | phase 3 |
| 1634 | C | True `--dry-run` | OPEN | | phase 3 |
| 1638 | C | Errored/unfinished run health | OPEN | | phase 3 |
| 1668 | C | NF mock/fakes contract + installer fixes | OPEN | | phase 3 |
| 1569 | C (+G tool) | Ontology extension namespace/SHACL/doctor | OPEN | | phase 4 |
| 1652-1662, 1665-1667 | G | Python/PyPI/ML tooling | OPEN | Grok PRs | Claude reviews |
| 1663 | G | 4.5.12 tracker | OPEN | | after children + release |

## PRs

| PR | Base | Purpose | State | Next |
|---|---|---|---|---|
| #1664 | `release/5.0.21` (retargeted from master 2026-11-17) | delete two stale `docs/prompts` notes | head updated from base (`01591268`); checks rerunning | independent review, then merge |

## Checkpoints

### 2026-11-17 (Claude, session 1)

- Branch `chore/5.0.21-ledger-ci` from `7642f407`: this ledger + CI routing.
- Next: open the ledger/CI PR, the tutorial-links PR, then `fix/1669-rh-percent-alias`.
