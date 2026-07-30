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

---

# Milestone C — DataFusion analytics cutover (2026-07-28)

**Status:** **Partial** on branch `milestone-c/c1-c2-analytics-runtime`.
Engine label: `central-analytics-v1` (DF SQL MemTable follow-up).
Docs: [`MILESTONE_C_CLOSEOUT.md`](../docs/migration/MILESTONE_C_CLOSEOUT.md),
[`MILESTONE_C_ACCEPTANCE.md`](../docs/migration/MILESTONE_C_ACCEPTANCE.md),
[`MILESTONE_C_ANALYTICS_MATRIX.md`](../docs/migration/MILESTONE_C_ANALYTICS_MATRIX.md),
[`MILESTONE_C_RULE_PARITY.md`](../docs/migration/MILESTONE_C_RULE_PARITY.md),
[`MILESTONE_C_ANALYTICS.md`](../docs/benchmarks/MILESTONE_C_ANALYTICS.md).

- [x] C0 — B adversarial verification + README / cookbook honesty
- [x] C1 — Analytics envelope + `/api/analytics/*` contracts
- [x] C2 — Runtime Δt compute + economizer diagnostics (live)
- [~] C3 — Sensor health minimal compute (coverage / flatline / stats)
- [~] C4 — Schedule occupied + after-hours fan hours (minimal)
- [~] C5 — Mechanical cooling evidence hierarchy (minimal; OAT bins residual)
- [~] C6 — Economizer live; RCx AHU coverage stub; full RCx UI residual
- [~] C7 — VAV comfort ranking minimal; full VAV RCx residual
- [ ] C8 — Plant evidence (chiller/boiler) — not started
- [~] C9 — Metering monthly kWh sum (minimal)
- [~] C10 — Rule parity fixture notes + mutation checklist (harness residual)
- [ ] C11 — Retire production pandas paths; filled benchmarks; `sha-*` acceptance

---

# Milestone D — Gaps bridge + WattLab / E+ (2026-07-28)

**Status:** **Partial** on branch `milestone-d/d1-historian-datafusion-runtime`.
Docs: [`MILESTONE_D_CLOSEOUT.md`](../docs/migration/MILESTONE_D_CLOSEOUT.md),
[`MILESTONE_D_ACCEPTANCE.md`](../docs/migration/MILESTONE_D_ACCEPTANCE.md),
[`MILESTONE_D_RULE_PARITY.md`](../docs/migration/MILESTONE_D_RULE_PARITY.md),
[`MILESTONE_D_GAP_REGISTER.md`](../docs/migration/MILESTONE_D_GAP_REGISTER.md).

- [x] D1 — Historian DataFusion bridge for runtime analytics
- [x] D2 — SQL rule parity mutation path check + CI + BUILDING_100 note
- [x] D3 — Job-native WattLab handoff UI (zip additive)
- [x] D4 — Restricted E+ runner policy + QUEUED persist stub (no in-process E+)
- [x] D5 — Vite `:5173` hint scrub + closeout / acceptance / gap register
- [ ] D4b — External runner claim loop + full artifact attach UX
- [ ] D2b — Logical gate mutations + `PROVEN_MULTI_BUILDING`
- [ ] D5z — Full-stack `sha-*` soak

---

# Liberty soak turnkey (2026-07-30) — post-064eadb

**Status:** open-fdd PR #601 · playground #69 **merged** (`2323f28` on develop).

- [x] Phase 0 — GH tidy + csv+caddy on `sha-064eadb`
- [x] OFDD-070b economizer CTE + OFDD-076b `building_id`→`site_id`
- [x] BUG-ECM-015 rows/`annual_usd` (playground)
- [x] OFDD-UI-BRAND + OFDD-MCP-CTX companion docs + pointers tool
- [x] OFDD-UI-SITE / JOBS (Hive picker, Delete…, Jobs expander off default)
- [x] OFDD-UI-V20 WattLab section + compose.wattlab + Caddy smoke
- [x] OFDD-069 findings draft persist + OFDD-065 Liberty deltas + MCP-IT doc
- [x] ECM-ERV-001 HAS_EP_PROTOTYPE residual stub (not product cascade)
- [ ] Merge #601 → GHCR `:sha-<final>` + `:nightly` → re-soak checklist
