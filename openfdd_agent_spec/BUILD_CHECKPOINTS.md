# Milestone A — build checkpoints

Track durable progress. Update whenever Milestone A status changes (merge,
blocker, or intentional exception). Detail:
[`MILESTONE_A.md`](MILESTONE_A.md),
[`docs/MIGRATION_MATRIX.md`](docs/MIGRATION_MATRIX.md),
[`docs/migration/MILESTONE_A_CLOSEOUT.md`](../docs/migration/MILESTONE_A_CLOSEOUT.md).

Legend: `[x]` done · `[~]` partial / residual · `[ ]` remaining

**Closeout status (2026-07-28):** Milestone A **closed with intentional residuals**
(see closeout doc). Milestone B Jobs may proceed.

---

## Phase 0 — Architecture freeze

- [x] Human architecture locks ([`ARCHITECTURE.md`](ARCHITECTURE.md))
- [x] Machine-readable seed ([`ownership.yaml`](ownership.yaml))
- [x] CI: ownership schema + cookbook path smoke (`scripts/architecture_ownership_check.py`)
- [~] Broader forbidden-import / terminology suites — residual harden
- [x] Required cookbook paths protected via ownership check + cookbook parity

## Phase 1 — Packaging / release / containers

- [x] PyPI `open-fdd` 4.1.0 / 4.1.1
- [x] vibe19 / UI pins `>=4.1.1,<5`
- [~] Version policy docs; generated manifest residual
- [~] Image metadata / nightly channel OK; deeper in-container asserts residual
- [x] Stack + MCP GHCR green post twin retirement

## Phase 2 — Shared contracts + rule manifest

- [ ] `open_fdd.contracts` — **deferred residual**
- [ ] Canonical rule manifest — **deferred residual**
- [~] Cookbook ↔ registry agreement via existing cookbook-parity

## Phase 3 — Vibe 19 thin-oracle cutover

- [x] Rules shims + runner/analytics package rebinds
- [x] Custom rules KEEP intentional
- [~] Full KEEP/SHIM/MOVE/DELETE matrix residual

## Phase 4 — Vibe 20 generic ECM migration

- [x] Eight twins delegated
- [~] Remaining keepers — residual / parallel track
- [x] Docker-socket runner = documented follow-on (not A blocker)

## Cross-cutting

- [x] Dual cookbooks present
- [x] Cookbook parity CI
- [x] Closeout audit committed
- [ ] Playground GHCR retirement — out of A

---

# Milestone B — Jobs / provenance (2026-07-28)

**Closeout status:** Milestone B **complete** (central SoT + UI thin client; see
[`MILESTONE_B_CLOSEOUT.md`](../docs/migration/MILESTONE_B_CLOSEOUT.md)).

- [x] B0 — Milestone A closeout audit (#583)
- [x] B1 — Job filesystem contract (#584)
- [x] B2 — Central `/api/jobs` filesystem store (#585)
- [x] B3 — Dataset refs + canonical fingerprint
- [x] B4 — Run records + statuses
- [x] B5 — Stale engine (`/stale`)
- [x] B6 — Findings + dispositions schemas + API
- [x] B7 — Streamlit Jobs on central API + stale banner
- [x] B8 — WattLab handoff manifest (job-native)
- [x] B9 — Acceptance doc + GHCR publish on merge
