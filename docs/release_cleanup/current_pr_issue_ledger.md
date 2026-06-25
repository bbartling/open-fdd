# Open-FDD release cleanup ledger

Updated: 2026-06-26 (validation reporting workflow PR)

## Current PRs

| PR | Title | Branch | CI | Blocks validation PR? | Decision |
|----|-------|--------|-----|----------------------|----------|
| **NEW** | Add local validation reporting workflow | `feature/local-validation-reporting-workflow` | pending | — | **Active — this PR** |
| [#383](https://github.com/bbartling/open-fdd/pull/383) | Rust Haystack driver for Niagara nHaystack | `feature/haystack-niagara-driver` | Rust CI failing (Docker) | No — merged into validation branch | **Leave open** until CI fixed; superseded by merge into #384 |
| [#381](https://github.com/bbartling/open-fdd/pull/381) | UI inspection build | `integration/ui-inspection-build` | Green | No — fast-forward merged into validation branch | **Leave open** until #384 merges; then close as superseded |
| [#382](https://github.com/bbartling/open-fdd/pull/382) | Docs cleanup Rust-only | `docs/rust-readme-docs-ci-cleanup` | Mostly green | No | **Leave open** — docs-only |

## Current issues

| Issue | Title | This PR | Decision |
|-------|-------|---------|----------|
| [#374](https://github.com/bbartling/open-fdd/issues/374) | Generic Data Export UI | Partial `/exports` on integration branch | **Keep open** — not in scope |
| [#369](https://github.com/bbartling/open-fdd/issues/369) | WASM sandbox | Not addressed | **Keep open** — deferred |
| **NEW** | Run 6-hour validation after 1-hour report workflow is stable | Future | **Create** if not run in this PR |

## Issue comments (if still open after merge)

- **#374:** Partial MVP exists on integration branch (`/exports` CSV downloads). Rich filters and last-export status remain future work.
- **#369:** WASM sandbox for custom connector transforms remains deferred; validation PR uses safe read-only drivers only.

## Local 1-hour validation

```bash
git checkout feature/local-validation-reporting-workflow
OPENFDD_ALLOW_LOCAL_BUILD=1 ./scripts/openfdd_inspection_build.sh --build
./scripts/openfdd_one_hour_validation_report.sh
```

Quick wiring (not acceptance): `OPENFDD_VALIDATION_QUICK_MINUTES=3 ./scripts/openfdd_one_hour_validation_report.sh`
