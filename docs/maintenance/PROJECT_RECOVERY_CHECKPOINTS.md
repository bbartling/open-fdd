# Project Recovery Checkpoints — 2026-07-10

Track sequential PR merges. Update after each phase.

| Phase | Branch / work | Status | Evidence |
| --- | --- | --- | --- |
| 0 | Recovery register | **DONE** | `docs/maintenance/PROJECT_RECOVERY_2026_07_10.md` @ `52a7d2c` |
| 1 | `fix/ghcr-publish-metadata-and-timeouts` | IN PROGRESS | Explicit tags; prune removed from publish; failure doc written |
| 2 | Stale/stuck Action runs + #486 | PENDING | — |
| 3 | `fix/consolidate-ci-and-isolate-rdf-tests` | PENDING | #479 #488 |
| 4 | Remote branch audit/cleanup | PENDING | #480 |
| 5 | `fix/dependency-security-and-action-runtime` | PENDING | #483 |
| 6 | FDD engine edge integration audit | PENDING | docs only |
| 7 | `feat/edge-fdd-engine-api` | PENDING | #481 prereq |
| 8 | `feat/react-fdd-phase-b` | PENDING | #481 |
| 9 | `feat/datafusion-canonical-50-rules` | PENDING | #482 |
| 10 | Full E2E validation report | PENDING | — |
| 11 | Issue/docs hygiene closeout | PENDING | — |

## Merge gate rule

Do not start a dependent phase until its blocking PR is merged and checks are green, except independent work (branch audit, security triage) which may proceed in parallel after Phase 1.
