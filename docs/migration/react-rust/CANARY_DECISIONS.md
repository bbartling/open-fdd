# P2-M3 — Canary promotion decisions

Evidence-based release decisions. Routing is **not** changed in this document;
P2-M4 performs the production default flip when authorized.

Release under evaluation: `master` tip at canary record time (post P2-M2 `#639`).
Streamlit fallback remains available until Prompt 7.

## Thresholds vs actuals (synthetic + Phase 1 gates)

| gate | threshold | actual | result |
|---|---|---|---|
| Shadow / parity defects | zero UNKNOWN / critical | shadow report PASS | PASS |
| Computation policy | no Python on React path | phase2_computation_policy_check OK | PASS |
| Core React workflows | not worse than Streamlit baseline | M4–M5 vitest + central APIs green in CI | PASS |
| Security / hostile upload | zero known privilege escalation | package.rs + Auth thin slice | PASS |
| Schema / rollback | expand-only; timed drill | ROLLBACK_DRILL.md | PASS |
| Migration telemetry | counters + events exist | `/api/ui/migration-metrics` | PASS |
| Ops large/concurrent soak | watch on canary | SKIP → observe via metrics post-flip | HOLD-WATCH |

## Stage decisions

| from → to | decision | evidence window | approvals | next review |
|---|---|---|---|---|
| maintainers synthetic | **PROMOTE** | Phase 1 qual + M1–M2 | turnkey 2026-08-01 | internal workflows |
| internal read-only | **PROMOTE** | React pages + APIs | turnkey 2026-08-01 | full workflows |
| internal full workflows | **PROMOTE** | M4–M5 capability paths | turnkey 2026-08-01 | selected operators |
| selected operators / 10% | **PROMOTE** | sticky cookie + fallback telemetry | turnkey 2026-08-01 | 25% |
| 25% → 50% → 100% w/ Streamlit fallback | **PROMOTE** | no P0/P1; fallback available | turnkey 2026-08-01 | **P2-M4 default flip** |

Overall: **PROMOTE** to 100% eligible sessions with Streamlit fallback still available.
Do **not** delete Streamlit or flip production env default in this PR.

## Red lines (none currently tripped)

- Critical result parity defect
- Authz regression
- Data integrity / orphan growth
- Unexplained DataFusion failure increase

## Open risks

- Historian metering rate→kWh remains PROVISIONAL
- 38 registry rules PROVISIONAL (`ported_from_cookbook`)
- CAP-WEATHER / CAP-ECM / CAP-SITE deferred

## Next action

P2-M4-01 React production default flip (routing/config only) — turnkey authorized.
