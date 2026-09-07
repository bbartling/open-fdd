---
name: Lab tuner Vibe19 parity program
overview: "Wave G after soft-OPEN — port Vibe19 robust Lab tuning into production (~217→~414). Low-RAM; 0 stale PRs / failed Actions. SQL/session-honest. Full Railway+ZAP closeout. Anomaly/hybrid parked/abandoned."
todos:
  - id: g-park-anomaly
    content: "Park anomaly; point BUG_REPORT at this program"
    status: pending
  - id: g0-gap-matrix
    content: "G0 — Vibe19 vs Lab gap matrix in BUG_REPORT; RCx docs linked"
    status: pending
  - id: g37-fc-thresholds
    content: "3.3.37 — FC GL36 Lab thresholds SQL-bound"
    status: pending
  - id: g38-sv-econ-vav
    content: "3.3.38 — SV/ECON/AHU/VAV/CHW residual Lab knobs"
    status: pending
  - id: g39-operational-gate
    content: "3.3.39 — Real operational-gate trio binding"
    status: pending
  - id: g40-lab-parity-chrome
    content: "3.3.40 — Lab chrome + post-wave snapshot"
    status: pending
  - id: g-closeout-full-stress
    content: "Closeout — full Railway stress with ZAP → BUG_REPORT CLOSED"
    status: pending
isProject: false
---

# Wave G — Lab tuner parity (Vibe19 → production)

**Parent Cursor plan:** `post_softopen_wave_g_sql_anomaly_master_f7a8b9c0.plan.md`  
**Living evidence:** [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../BUG_REPORT_OT_MODBUS_HAYSTACK.md) · [`STRESS_CLOSEOUT.md`](../STRESS_CLOSEOUT.md) · [`PATCH_CYCLE.md`](../PATCH_CYCLE.md)  
**Snapshots:** [`recovery/vibe19_ui_tuners_snapshot.json`](../recovery/vibe19_ui_tuners_snapshot.json) (target **414**) · Lab tip ~**217**  
**RCx out-of-box plots by HVAC type:** [`RCX_PLOTS_BY_HVAC.md`](../../RCX_PLOTS_BY_HVAC.md)

## Intent

Production Lab must be **as robust as the Vibe19 prototype** for rule tuning. Rules already parity (62↔68); **tuners** do not. Close the gap with SQL/session-honest registry parameters.

## Low-RAM + GH hygiene (every child)

- **No** local `docker build` of hub images; pull GHCR `sha-*`; prune images; stop ZAP leftovers
- Field = x86 fieldbus only (no Pi in stress)
- **GH hygiene START/END:** **0 open/stale PRs**; only tip branch; **tip Actions green** (no failed workflows)
- Wait GHCR Publish before Railway re-pin; do not merge docs mid-Publish

## Child revs

| Rev | Concern |
|-----|---------|
| **3.3.37** | FC GL36 residuals: `mode_delay_min`, `eps_*`, `econ_full_open`, `fan_on_min`, FC14/15 |
| **3.3.38** | SV spike/rate; ECON/AHU/VAV/CHW leftover thresholds |
| **3.3.39** | Operational-gate trio **with real binding** (unblocks ~156 Vibe slots) |
| **3.3.40** | Lab UI + regenerate `lab_tuners_snapshot_post_wave_g.json` |

## Stress

Mid-wave smoke; **closeout** = full `run_railway_hub_stress.sh` (ZAP on) → `fully_qualified` → BUG_REPORT.

## Parked / abandoned

- SQL anomaly — **PARKED** ([`openfdd_sql_anomaly_screening_program.plan.md`](openfdd_sql_anomaly_screening_program.plan.md))
- Hybrid physics/RCA — **ABANDONED**

## Honesty

Every Lab slider must change rule SQL or session gating. No no-op chrome.
