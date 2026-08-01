# Cutover log

Phase 2 operational record. Newest first.

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
