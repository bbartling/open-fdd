# P2-M0-03 — Schema compatibility + timed Streamlit rollback drill

## Schema / data compatibility

- Job/meta/findings/dispositions writes remain **expand-only** during Phase 2:
  new optional fields may appear; Streamlit fallback must ignore unknowns.
- React and Streamlit share the same Rust job store (`OPENFDD_WORKSPACE/jobs`).
- No destructive schema contraction in the same release as a UI flip.
- Optimistic concurrency (`meta_revision`, findings_revision) works from both UIs.

## Timed rollback drill (config only)

Target RTO: **≤ 15 minutes** (operator + compose).

1. Record start UTC time.
2. Confirm React cohort path healthy: `curl -sf http://localhost:8080/api/capabilities` and `/api/ui/generation`.
3. Stop React topology:
   ```bash
   docker compose -f docker/compose.react.yml down
   ```
4. Start Streamlit fallback topology (same workspace volume):
   ```bash
   docker compose -f docker/compose.central.yml up -d
   ```
5. Verify Streamlit UI on `:3000` and central `:8080/api/health`.
6. Optional: clear React sticky cookie / set generation streamlit:
   ```bash
   curl -sf -X PUT http://localhost:8080/api/ui/generation \
     -H 'content-type: application/json' \
     -d '{"generation":"streamlit","reason":"rollback_drill"}'
   ```
7. Record end UTC; attach durations to CUTOVER_LOG.

**Does not** rewrite jobs, findings, or artifacts. Rollback changes routing/compose only.

## Post P2-M4 note

Production default generation is **React**. `compose.central.yml` pins
`OPENFDD_UI_GENERATION_DEFAULT=streamlit` so the Streamlit stack remains an
explicit rollback path without rebuilding images.
