# Phase 2 qualification — production no-Python release

**Commit under qualification:** `47ae7b5` (P2-M6) + this pack on merge.  
**Verdict:** **PASS** (with accepted risks below).

## Topology

| surface | status |
|---|---|
| Product UI | React SPA (`frontend/web`, `compose.react.yml`) |
| APIs / domain | central Rust |
| FDD / deterministic analytics | DataFusion SQL |
| Production Python runtime | None on product compose path |

## Gates

| gate | evidence | result |
|---|---|---|
| Rust fmt/clippy/workspace CI | required Actions on P2 merges | PASS |
| React lint/type/unit/build | `react-web` job | PASS |
| Computation policy | `phase2_computation_policy_check.py` | PASS |
| Shadow compare | `phase2_shadow_compare.py` + `evidence/shadow/` | PASS |
| Architecture React policy | `architecture_react_policy_check.py` | PASS |
| No-Python compose | `compose.react.yml` config | PASS |
| Cutover control plane | `/api/ui/generation` default React; flipped | PASS |
| Canary | `CANARY_DECISIONS.md` PROMOTE | PASS |
| React product exit | `PHASE_2_QUALIFICATION.md` | PASS |
| Python exit matrix | zero BLOCKED; React entry DELETED from product | PASS |
| Security / Trivy / Gitleaks / Hadolint | AppSec + Stack Security | PASS |
| Hostile upload | package.rs + UploadPage | PASS |
| Full browser a11y/visual harness | not re-run as dedicated suite in P2 | SKIP → accepted; Phase 1 vitest + CI proxy |
| Host without Python for product services | compose.react images (Rust/nginx) | PASS (config) |
| Upgrade from last release | GHCR immutable digests | DOCUMENTED |

## Capability summary

| status | capabilities |
|---|---|
| React product path (DONE for Phase 2) | AUTH, UPLOAD, JOBS, MAP, RULES, OVERVIEW, PLOTS, RCX (stub), METER, FINDINGS, REPORTS, WATTLAB |
| Deferred / non-product | SITE, WEATHER, ECM, ERRORS depth |
| Registry honesty | 24 PROVEN / 38 PROVISIONAL / 1 DISABLED |

## Accepted risks

1. Historian metering rate→kWh remains PROVISIONAL.
2. 38 SQL rules PROVISIONAL (`ported_from_cookbook`).
3. Oracle Python retained for cookbooks/PyPI only; product path does not start it.
4. CAP-WEATHER / CAP-ECM / CAP-SITE not React-complete (ORACLE / KEEP-AS-LIB / DEFER).

## Digests

Pin immutable digests from the GHCR publish run for the qualification SHA after merge.

## Phase 3 readiness

Phase 2 cutover/deletion program is **complete for product topology**. Phase 3 may deepen PROVISIONAL rules, historian metering, weather/ECM React, and edge streaming.

**Phase 2 exit: APPROVED.**
