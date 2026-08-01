# Cutover log

Phase 2 operational record. Newest first.

## 2026-08-01 — GHCR nightly refresh verified @ 61fee63

- Stack publish success: Actions run 30710271297 (`sha-61fee63` + `:nightly` retarget).
- MCP publish success: 30710271292.
- Local pull: nightly↔sha digests match for central/ui/fieldbus/mqtt/mcp (see `PHASE_3_READINESS.md` Digests).
- `compose.react.yml` config OK; `openfdd-web` not in GHCR yet.

## 2026-08-01 — GHCR nightly refresh verified @ 9ef0411

- Stack publish success: Actions run 30708116225 (`sha-9ef0411` + `:nightly` retarget).
- MCP publish success: 30708116291.
- Superseded by tip `61fee63` digest record.

## 2026-08-01 — Phase 3 readiness (outlook only)

- Evidence: `PHASE_3_READINESS.md`. No P3-M0+ implementation; no BACnet/MQTT changes.
- Skill compliance PASS; agent_spec post–Phase-2 truth update in same pack.

## 2026-08-01 — Phase 2 exit APPROVED

- Qualification: `PHASE_2_QUALIFICATION.md` **PASS**.
- React is sole production UI; no product Python runtime on `compose.react.yml`.
- Streamlit recovery: `ARCHIVED.md` + `streamlit-legacy` profile / GHCR digests.

## 2026-08-01 — P2-M6 Streamlit product removal

- Product path no longer starts Streamlit by default.
- Recovery: `ARCHIVED.md` + `--profile streamlit-legacy` + historical GHCR digests.
- Next: Prompt 8 final no-Python qualification.

## 2026-08-01 — P2-M5 fallback observation closed

- Streamlit is emergency rollback only. Leaf twin deletion deferred to Prompt 7 vehicle.
- See `FALLBACK_CLOSEOUT.md`.

## 2026-08-01 — P2-M4 React default flip

- Time: 2026-08-01 (turnkey auth). Config: `OPENFDD_UI_GENERATION_DEFAULT` default → `react`.
- `production_default_flipped: true`. Streamlit fallback still available (cookie / compose.central).
- Observation: migration metrics + fallback_click. Next: P2-M5 leaf twin deletion after observation note.

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
