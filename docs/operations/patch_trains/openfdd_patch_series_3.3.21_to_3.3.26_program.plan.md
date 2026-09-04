---
name: Open-FDD patch series 3.3.21→3.3.26
overview: "Program index (not a shipping rev). Sequential low-RAM patch cycles: finish 3.3.21 closeout → One Dump IA → Faults Lab declutter → three phased Lab tuner waves. Each child plan owns hygiene, GHCR, Railway re-pin, x86 fieldbus, CSV+ZAP stress, BUG_REPORT logging. Skip allowed only with DEFERRED row in BUG_REPORT."
todos:
  - id: close-321
    content: "Execute 3.3.21_closeout plan — re-pin/stress/BUG_REPORT only (product already merged)"
    status: pending
  - id: ship-322
    content: "Execute 3.3.22_one_dump_ia — single Dump page; ingest only in left rail"
    status: pending
  - id: ship-323
    content: "Execute 3.3.23_faults_lab_declutter — category-first Lab; less Faults chrome"
    status: pending
  - id: ship-324
    content: "Execute 3.3.24_tuners_gl36 — registry+Lab GL36 FC threshold parity wave"
    status: pending
  - id: ship-325
    content: "Execute 3.3.25_tuners_sv_econ_ahu — SV/ECON/AHU/VAV missing Lab params"
    status: pending
  - id: ship-326
    content: "Execute 3.3.26_tuners_gates_residual — optional gate trio + soft-OPEN triage"
    status: pending
isProject: false
---

# Open-FDD patch series — 3.3.21 closeout through 3.3.26

**Not a shipping VERSION bump.** This file is the program index. Open **one child plan at a time**. Do not start the next child until the previous child’s BUG_REPORT verdict exists (CLOSED or DEFERRED with reason).

## Decisions locked (operator left design to agent)

| Topic | Choice |
|-------|--------|
| Order | Closeout → **One Dump / IA** → **Faults Lab declutter** → **Tuner waves** |
| Tuners | **Phased**, SQL-honest: Wave1 GL36 FC gaps → Wave2 SV/ECON/AHU → Wave3 optional gate trio. **Not** a hard “414 = success” — success = every Lab slider substitutes real SQL / session params; Vibe19-only leftovers logged DEFERRED |
| Topology | Railway hub (central→mqtt→web) + bensbench **x86 fieldbus** only + light ZAP. **No** Pi. **No** local `react-ot` as AFDD head-end. **No** local `docker build` |
| Hygiene | Every child: START+END — **0** open PRs, **only** `master`, tip Actions green, delete merged remote branches, no unexplained failed tip runs |
| Skip | Allowed mid-rev for out-of-scope or blocked items — must add **DEFERRED** row in BUG_REPORT with why + next rev id |

## Child plans (open these)

| Rev | Plan file | One concern |
|-----|-----------|-------------|
| 3.3.21 closeout | [`3.3.21_closeout_railway_stress.plan.md`](3.3.21_closeout_railway_stress.plan.md) | Finish re-pin + stress + BUG_REPORT (product already on master) |
| 3.3.22 | [`3.3.22_one_dump_ia.plan.md`](3.3.22_one_dump_ia.plan.md) | One Dump; kill Export&ML multi-page confusion; ingest left-rail only |
| 3.3.23 | [`3.3.23_faults_lab_declutter.plan.md`](3.3.23_faults_lab_declutter.plan.md) | Faults/Lab UX — category-first, less “settings on faults” overload |
| 3.3.24 | [`3.3.24_tuners_gl36_wave.plan.md`](3.3.24_tuners_gl36_wave.plan.md) | Lab/registry GL36 FC threshold expansion |
| 3.3.25 | [`3.3.25_tuners_sv_econ_ahu_wave.plan.md`](3.3.25_tuners_sv_econ_ahu_wave.plan.md) | Lab/registry SV / ECON / AHU / VAV missing keys |
| 3.3.26 | [`3.3.26_tuners_gates_residual.plan.md`](3.3.26_tuners_gates_residual.plan.md) | Optional operational-gate Lab knobs + soft-OPEN triage |

Evidence inventory (tuners): canvas `vibe19-openfdd-rule-tuners` — Vibe19 ~414 UI vs Open-FDD Lab ~184.

## Shared loop (every shipping child)

```text
hygiene START → (VERSION bump if shipping) → one product concern → one PR
  → squash-merge --delete-branch → wait GHCR Publish sha-<7>
  → Railway backup → re-pin central→mqtt→web → x86 fieldbus up
  → run_railway_hub_stress.sh (CSV + ZAP) LAST
  → BUG_REPORT Verdict 3.3.N + SESSION_LOG paths → hygiene END
```

Canonical ops: [`open-fdd/docs/operations/PATCH_CYCLE.md`](../PATCH_CYCLE.md) · [`STRESS_CLOSEOUT.md`](../STRESS_CLOSEOUT.md) · living log [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../BUG_REPORT_OT_MODBUS_HAYSTACK.md).

## BUG_REPORT logging contract (every child)

Append **Verdict — 3.3.N** table with at least:

- Product PR + tip SHA + VERSION
- GHCR `sha-<7>` + Publish URL
- Railway backup dir
- Hub re-pin order proof + health `3.3.N+…`
- Fieldbus `sha-<7>` + `/api/edges` telemetry
- Stress artifact dirs (synth59, gate17, B100, Creekside, gate19, ZAP)
- **Shipped** bullets for this rev’s product concern
- **DEFERRED / SKIPPED** rows (id, reason, next rev) — never silent skip
- Soft-OPEN updates if touched

Evidence-only follow-up PR (docs/BUG_REPORT/SESSION_LOG) may land **without** VERSION bump.

## Explicit non-goals (program-wide)

- Raspberry Pi back on Open-FDD closeout
- Local docker build of central/web/fieldbus
- Reopening ML/vibe20 depth (#763/#805 closed foundation)
- Authenticated deep ZAP / bug bounty
- Force-push / `--no-verify` / secrets in git or Discord→git
- Parallel open feature PRs across children (one train at a time)

## How to run

1. Finish [`3.3.21_closeout_railway_stress.plan.md`](3.3.21_closeout_railway_stress.plan.md) first if hub still on `3.3.20` / `sha-aef6fc1`.
2. Then open 3.3.22 … 3.3.26 in order.
3. After each CLOSED verdict, mark the matching todo on **this** program file completed.
