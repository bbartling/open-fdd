---
name: Haystack RDF C6 candidate rollout
overview: "Immutable candidate tip, backup, disposable smoke, rollback rehearsal, enhanced gate-36 qualification evidence, milestone disposition for HR-01–HR-12."
todos:
  - id: c6-backup-pin
    content: "Railway/local backup → pin candidate sha-* / semver"
    status: pending
  - id: c6-smoke
    content: "Scoped disposable-fixture smoke on candidate"
    status: pending
  - id: c6-rollback
    content: "Rollback rehearsal preserves native metadata + historian"
    status: pending
  - id: c6-enhanced
    content: "Enhanced gate-36 + required HR matrix evidence window"
    status: pending
  - id: c6-closeout
    content: "Fill master evidence table; BUG_REPORT/MILESTONES disposition; limitations visible"
    status: pending
isProject: false
---

# C6 — Candidate rollout and closeout

**Parent:** [`wave_haystack_rdf_master.plan.md`](wave_haystack_rdf_master.plan.md)  
**Depends on:** C5 evaluator integrity green; C1–C4 tips published  
**HR:** all HR-01–HR-12 evidence closeout (verification ≠ release)

## Implementation / ops tasks

1. **Candidate identity:** record product SHA, image digests (`./scripts/ghcr_newest_by_created.py`), profile/schema/fixture hashes, harness SHA, tool versions.
2. **Backup** before re-pin (Railway CLI skill / local volume policy — never `docker compose down -v`).
3. **Smoke:** disposable synthetic Haystack fixtures only; no live customer model mutation; no OT required.
4. **Rollback rehearsal:** pin prior `sha-*`; confirm old ZIP import + historian intact + metadata authority restored.
5. **Enhanced qualification:** run gate 36 (and stress profile rows that include it) on candidate; consume C5 required-set; **do not** treat older green S4/V6 windows as Haystack profile acceptance.
6. **Closeout:**
   - Fill master evidence table HR-01–HR-12
   - Update `BUG_REPORT_WAVE_P.md`, `WAVE_U_MASTER.md` Soft-OPEN → CLOSED/PARTIAL with limitations
   - `MILESTONES.md`: separate implementation / verification / release
   - Remaining HR-10 Option B or HR-11 PARTIAL stay visible

## Permanent tests

- No new product features in C6 unless hotfix for qualification FAIL.
- Re-run C5 negatives against candidate harness identity.

## CI / stress commands

```bash
# Discover live pin tooling at execute time; typical pattern:
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web
# backup + re-pin per openfdd-railway-cli skill / LOCAL_DEPLOYMENT
ARTIFACT_DIR=reports/haystack_rdf_c6_<UTC> \
  bash scripts/nightly-ot-bench/36_model_ecm_qualification.sh
# If hub stress profile includes gate 36:
# scripts/nightly-ot-bench/run_railway_hub_stress.sh  # only when scheduled; smoke mid-tips otherwise
```

Exact stress entrypoint and Railway project from current ops docs at execute time — do not resurrect stale MEGA windows.

## Docs

- Final profile limitations section
- Public onboarding works without Ben Downloads / live BAS

## Rollback criteria

- Any HR-01 regression on old ZIP → immediate prior pin
- Historian data loss → abort promotion; restore backup
- Evaluator softening to pass → **forbidden**; leave Soft-OPEN

## Exit criteria

- [ ] Candidate digests + fixture hashes recorded
- [ ] Smoke PASS on disposable fixtures
- [ ] Rollback rehearsal PASS
- [ ] Enhanced gate-36 evidence path with nonzero FAIL on broken control fixtures
- [ ] Master HR evidence table filled; no greenwash
- [ ] Release claim only if milestones process explicitly promotes (separate from verification)
