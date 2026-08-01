# Cutover log

Phase 2 operational record. Newest first.

## 2026-08-01 — P2-M3 canary PROMOTE

- Decision record: `CANARY_DECISIONS.md` — PROMOTE to 100% with Streamlit fallback.
- Production default **not** flipped here. Next: P2-M4.

## 2026-08-01 — P2-M2 shadow/soak PASS

- Shadow report: `evidence/shadow/latest_shadow_report.json` (no production findings write).
- Soak: `SHADOW_SOAK.md` synthetic gate PASS; ops large/concurrent watch deferred to canary metrics.
- Next canary prerequisite: P2-M3 promotion record.

## 2026-08-01 — P2-M1-01 computation closure

- Ledger: `COMPUTATION_CLOSURE.md`. Policy: `scripts/phase2_computation_policy_check.py`.
- Production React path: no Python computation. Turnkey auth to continue Prompts 2–8.
- Next: P2-M2 shadow/soak → M3 canary → M4 default flip → twin deletion.

## 2026-07-31 — P2-M0-02 / P2-M0-03 telemetry + rollback

- Migration metrics: `GET /api/ui/migration-metrics` + `POST /api/ui/migration-event` (fallback_click / ui_error / datafusion_skip).
- Rollback drill doc: `ROLLBACK_DRILL.md` (compose.react → compose.central, expand-only schema).
- **Stop for human** before Prompt 2+ (computation closure / canary / deletion).

## 2026-07-31 — P2-M0-01 cohort routing

- Added `/api/ui/generation` (cookie + header + env default).
- Production default **not** flipped (`production_default_flipped: false`).
- Audit: `$OPENFDD_WORKSPACE/.cache/cutover_audit.jsonl`

## 2026-07-31 — Phase 1 exit approved; Phase 2 not started

- Qualification: `PHASE_1_QUALIFICATION.md`
- No-Python stack: `docker/compose.react.yml`
- Deletion candidates enumerated: `PHASE_2_DELETION_CANDIDATES.md`
- Production default UI remains Streamlit (`compose.central.yml` `ui` service)
- Next: P2-M0-01 cohort/flag routing (do **not** flip production default)
