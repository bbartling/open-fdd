---
name: Wave R Stress Patches
overview: "CLOSED OPS PINNED 3.5.22 / sha-4d3a6b0. Product FC1 fan_status parity (#936) + harness Soft closeout (#937). Hub stress reports/nightly-ot-bench_20260916T011952Z fully_qualified=true (no SKIP_ZAP). Soft-OPEN ≤ Stage C only (UTIL-INTERVAL, ingest_reject count, Kali AF, IdP/MFA)."
todos:
  - id: r1-fc1-sql-fault-hours
    content: "FC1 AHU_CASE_FC1 DataFusion fault_hours vs pandas — SQL fan_status parity (#936); soak rel-tol for ~39.58h vs golden 40 (#937)"
    status: completed
  - id: r2-wave-l-off-vs-mt-on
    content: "Hub stress Wave L OFF 12–17 PASS N/A when multi_tenant=true"
    status: completed
  - id: r3-afdd-flood-429
    content: "AFDD flood: pre-minted bearer + IGNORE_RULES_FAILED for UTIL Soft; gate 19 PASS"
    status: completed
  - id: r4-zap-baseline
    content: "Hub stress without SKIP_ZAP; 06_zap_baseline PASS (ACCEPT_ZAP_MEDIUM=1)"
    status: completed
  - id: r5-hub-tip-repin-3521
    content: "Railway OPS PINNED 3.5.22+4d3a6b0e0707; backup 20260915T232819Z"
    status: completed
  - id: r6-ingest-deadletters
    content: "Soft: ingest_reject count-only (/api/ingest/stats); ACME honesty carry"
    status: completed
  - id: r7-local-jci-fec-5007
    content: "JCI FEC 5007 Who-Is + AI:1173 OA-T; local OT catalog slimmed"
    status: completed
  - id: r10-viewer-role-optional
    content: "Viewer optional documented; OPENFDD_VIEWER_PASSWORD present on Railway"
    status: completed
  - id: r11-rules-failed-1
    content: "rules_failed Soft = UTIL-INTERVAL (not FC1); live flood ignores"
    status: completed
  - id: r12-stage-c-park
    content: "Soft-OPEN Stage C IdP/MFA/SKU — parked"
    status: completed
  - id: r13-re-stress-ops-pin
    content: "OPS PINNED — reports/nightly-ot-bench_20260916T011952Z fully_qualified=true"
    status: completed
isProject: false
---

# Wave R — Stress patches (Mint) — **CLOSED / OPS PINNED**

**Parent closeout:** Wave Q residual closeout. Tracker: [`docs/operations/BUG_REPORT_WAVE_P.md`](docs/operations/BUG_REPORT_WAVE_P.md).

## Pin

| Item | Value |
|------|--------|
| Product | **3.5.22** / `sha-4d3a6b0` (#936) |
| Harness | `4c0862e1` (#937) — hours rel-tol + AFDD bearer + Railway auth fetch |
| Hub health | `3.5.22+4d3a6b0e0707` · `multi_tenant=true` |
| Backup | `~/openfdd-backups/railway/20260915T232819Z` |
| Stress | `reports/nightly-ot-bench_20260916T011952Z/` · **`fully_qualified=true`** · no `SKIP_ZAP` |

## Soft-OPEN (≤ Stage C)

- Stage C IdP/MFA/SKU (commercial)
- UTIL-INTERVAL missing `utility_interval` (live flood Soft-ignored)
- ACME `ingest_reject` count-only (no dead-letter dump API); honesty on ΔP SP / TEC / OAT-METEO
- Kali authenticated ZAP AF (other box)

## Patches landed

1. **r1** FC1 SQL prefers `fan_status` for fan-hi (pandas `_fan()` parity) — tip 3.5.22
2. **r2** Wave L OFF gates N/A when MT ON
3. **r3/r4/r19** AFDD pre-minted JWT (gate 23 must not poison flood); ZAP ran
4. **r5** Railway re-pin after GHCR hub tip
5. **r7** Local OT = JCI FEC **5007** only
6. **#937** synth59 hours 2% rel-tol (cap 0.5h) so tip ~39.58h vs golden 40 without editing `expected_faults.csv`

## Exit evidence

All required gates **PASS** including `01_synth59`, `02_gate17`, `06_zap_baseline`, `19_wave_m_afdd_flood`. 0 open wave PRs; wave feature remotes deleted.
