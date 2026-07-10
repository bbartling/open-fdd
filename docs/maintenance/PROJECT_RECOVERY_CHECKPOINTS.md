# Project Recovery Checkpoints — 2026-07-10

Track sequential PR merges. Update after each phase.

| Phase | Branch / work | Status | Evidence |
| --- | --- | --- | --- |
| 0 | Recovery register | **DONE** | `docs/maintenance/PROJECT_RECOVERY_2026_07_10.md` |
| 1 | `fix/ghcr-publish-metadata-and-timeouts` | **MERGED** | PR #490 → `c5febe45`; GHCR validation run `29094833935` |
| 2 | Stale/stuck Action runs + #486 | IN PROGRESS | No live stuck runs; awaiting green publish |
| 3 | `fix/consolidate-ci-and-isolate-rdf-tests` | IN PROGRESS | Delete duplicate `ci.yml`; RDF store race fix |
| 4 | Remote branch audit/cleanup | IN PROGRESS | 16 remotes deleted; hold `chore/product-gh-actions-deep-sleep` |
| 5 | `fix/dependency-security-and-action-runtime` | PENDING | #483 (2 moderate Dependabot) |
| 6 | FDD engine edge integration audit | **DONE (doc)** | `docs/architecture/FDD_ENGINE_EDGE_INTEGRATION_AUDIT.md` |
| 7 | `feat/edge-fdd-engine-api` | PENDING | #481 prereq |
| 8 | `feat/react-fdd-phase-b` | PENDING | #481 |
| 9 | `feat/datafusion-canonical-50-rules` | PENDING | #482 |
| 10 | Full E2E validation report | PENDING | — |
| 11 | Issue/docs hygiene closeout | PENDING | — |

## Merge gate rule

Do not start a dependent phase until its blocking PR is merged and checks are green, except independent work (branch audit, security triage) which may proceed in parallel after Phase 1.
