---
name: Post-3.3.33 soft-OPEN master
overview: "Soft-OPEN D→E→F then ONE full Railway stress LAST. After OT closeout, optional Wave G starts the experimental semantic hybrid ML/Physics AHU+VAV slice — separate from OT qualification; never claim scientific validation from Railway stress alone."
todos:
  - id: wave-d-ingest
    content: "Wave D — 3.3.34 MQTT ingest resilience (ingest_ok advancing after re-pin); Railway smoke + reconnect proof (no full matrix mid-wave)"
    status: pending
  - id: wave-e-ui
    content: "Wave E — 3.3.35 railway-ui-fdd-stale + bldg2 Overview browser sign-off; Railway smoke + Overview probe"
    status: pending
  - id: wave-f-lab
    content: "Wave F — 3.3.36 Lab residual (DEFER dishonest operational-gate) + optional auth_matrix viewer; isolated/unit + smoke"
    status: pending
  - id: closeout-full-stress
    content: "Soft-OPEN closeout — ONE full run_railway_hub_stress.sh on final tip → fully_qualified + Overview MQTT gate → BUG_REPORT D–F CLOSED"
    status: pending
  - id: wave-g-hybrid
    content: "Wave G (AFTER closeout) — experimental semantic hybrid diagnostics AHU+VAV first vertical slice; child revs 3.3.37+; synthetic gates primary; no merge/deploy without separate auth"
    status: pending
isProject: false
---

# Open-FDD post-3.3.33 soft-OPEN master — optimized

**Not a VERSION bump itself.** Child plans are the concern backlog. Parent program [`openfdd_nightly_bug_train_3.3.27_plus_program.plan.md`](openfdd_nightly_bug_train_3.3.27_plus_program.plan.md) is **CLOSED** through 3.3.33.

**Honesty rule:** every concern still gets evidence. Drop only **duplicate full Railway matrices** between OT children.

**Preferred OT stress shape:** mid-wave **smoke / isolated**; **ONE full** `run_railway_hub_stress.sh` **LAST** (soft-OPEN closeout) before the BUG_REPORT D–F verdict.

**Gate:** Fix live ingest stall (Wave D) before UI polish (Wave E). Do not merge docs mid-Publish.

**Mirrors:** this `patch_trains/` dir + `~/.cursor/plans/post_3.3.33_soft_open_master_a1b2c3d4.plan.md`. Living evidence: [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../BUG_REPORT_OT_MODBUS_HAYSTACK.md).

**Baseline tip (start):** `25826cf6` · **`sha-25826cf`** · health **`3.3.33+25826cf67999`** · field `bldg2` / `pi-1` · hosted AV `9101` → `bldg2-zone-loopback` / `zone_t`.

## Would Wave G (hybrid ML/Physics) be nuts?

**Nuts if:** jammed into D/E/F, one mega-PR, OT full stress treated as scientific validation, green Overview cells for unsupported families, Python in central request paths, promoting `eplus_dump_clustering_export.py` zero-fill KMeans into product, merge/deploy without separate authorization.

**Not nuts if:** **after** soft-OPEN closeout; **separate experimental product train**; incremental reviewable children; AHU+VAV first slice only; explicit not-applicable/insufficient states; synthetic-59 + unit gates primary; Railway smoke only after images ship and **never** marketed as Guideline-14 / production-qualified ML.

## Waves (do this)

```mermaid
flowchart LR
  waveD[WaveD_ingest_smoke]
  waveE[WaveE_ui_smoke]
  waveF[WaveF_lab_isolated_smoke]
  closeout[Closeout_ONE_full_Railway_stress]
  waveG[WaveG_hybrid_AHU_VAV_experimental]
  waveD --> waveE --> waveF --> closeout --> waveG
```

| Wave | Children | Ship how | Stress (required) |
|------|----------|----------|-------------------|
| **D — ingest** | [`3.3.34`](3.3.34_mqtt_ingest_reconnect.plan.md) | MQTT ingest reconnect; VERSION if GHCR ships | **Railway smoke** + `ingest_ok` advance ≥2 intervals |
| **E — UI** | [`3.3.35`](3.3.35_overview_ui_fdd_scope.plan.md) | `railway-ui-fdd-stale` + Overview tables-visible | **Railway smoke** + Overview probe + browser sign-off |
| **F — Lab residual** | [`3.3.36`](3.3.36_lab_gate_residual.plan.md) | Honest Lab only; Path B refuse fake gates | **Isolated/unit** + **Railway smoke** |
| **Closeout** | — (same final tip) | No new product unless tip moved | **ONE full** Railway → `fully_qualified` → **BUG_REPORT D–F CLOSED** |
| **G — hybrid diagnostics** | [`openfdd_hybrid_diagnostics_ahu_vav_program.plan.md`](openfdd_hybrid_diagnostics_ahu_vav_program.plan.md) · revs **3.3.37+** | Experimental semantic ML/Physics column + EnergyPlus calibration export; **AHU+VAV first vertical slice** | **Synthetic/unit/contract primary**; Railway smoke after image tips; **do not** claim scientific validation from OT full stress |

### Soft-OPEN child index

| Rev | Plan | One concern |
|-----|------|-------------|
| 3.3.34 | `3.3.34_mqtt_ingest_reconnect.plan.md` | Central MQTT ingest stays live after mqtt/central redeploy |
| 3.3.35 | `3.3.35_overview_ui_fdd_scope.plan.md` | Building-scoped FDD chrome + Overview tables visible by default |
| 3.3.36 | `3.3.36_lab_gate_residual.plan.md` | Honest Lab residual; **DEFER** vibe19 operational-gate if no SQL truth |

### Wave G child index (after closeout — experimental)

| Rev | Plan (under patch_trains) | One concern |
|-----|---------------------------|-------------|
| 3.3.37 | `3.3.37_hybrid_semantic_applicability.plan.md` | Versioned detector/feature manifests + applicability states (AHU/VAV supported; others explicit N/A) |
| 3.3.38 | `3.3.38_hybrid_feature_pipeline.plan.md` | Shared DataFusion/Arrow feature dataset; no zero-fill of missing physics |
| 3.3.39 | `3.3.39_hybrid_regimes_deviation.plan.md` | Seeded KMeans regimes + within-regime deviation jobs/artifacts (real train/score) |
| 3.3.40 | `3.3.40_hybrid_physics_ahu_vav.plan.md` | AHU mixing + VAV sensible residuals with observability gates |
| 3.3.41 | `3.3.41_hybrid_overview_ml_physics.plan.md` | Overview **ML / Physics** column + evidence drilldown (no Plotly on Overview) |
| 3.3.42 | `3.3.42_hybrid_eplus_research_export.plan.md` | EnergyPlus calibration purpose (primary) + research reproducibility bundle |

Full mission text / gates: child program plan. Proposal originally inspected `40ac0664` (2026-09-05); **recheck tip before implementing**.

## Soft-OPEN → wave map (from BUG_REPORT)

| ID | Disposition entering this program | Wave |
|----|-----------------------------------|------|
| **mqtt-ingest-stall** | **OPEN** | **D** |
| **mqtt-fieldbus-tip-pin-sync** | **CLOSED** on 3.3.33 tip | — |
| **railway-ui-fdd-stale** | **DEFERRED** → UX | **E** |
| **bldg2-overview-signoff** | **DEFERRED** → operator browser | **E** |
| **vibe19-operational-gate-lab** | **DEFERRED** (no honest SQL) | **F** or stay DEFERRED |
| **qualification-viewer-login** optional matrix path | soft | **F** optional |
| **hybrid-ml-physics-ahu-vav** | **OPEN** → experimental product | **G** (after OT closeout) |
| **weather-legitimacy-chicago** | tier-C optional | out of wave |
| **railway-f1-stress** B50/AFDD | operator-skip | out of wave |
| **local-parquet-root-split** | lab-only | out of wave |

## Stress tiers (not cheat — right tier)

| Tier | When | What |
|------|------|------|
| **Full Railway** | Soft-OPEN **closeout only** (preferred) | Full `run_railway_hub_stress.sh` → `fully_qualified` + Overview MQTT=`CSV` → BUG_REPORT D–F |
| **Railway smoke** | End of D / E / F; after Wave G image tips | Hub + fieldbus + edges + **`ingest_ok` advancing** + Overview; G adds hybrid endpoint smoke only |
| **Isolated / unit / synthetic** | F Lab; **all of Wave G** | Reconnect units; hybrid feature/train/score/export/Overview state tests; synthetic-59 regression |
| **Wave G honesty** | Always | OT full stress **≠** ML scientific acceptance; disable research claims until labeled/held-out gates pass |

### Full / smoke MUST still validate MQTTS → Overview (OT waves)

| Check | Expected |
|-------|----------|
| Field | x86 fieldbus → MQTTS; hosted-weather AV **9101** |
| Edge | `pi-1` / `bldg2` `has_telemetry:true` |
| Ingest | `ingest_ok` **increases** across ≥2× publish interval |
| Role | **`zone_t`** / `bldg2-zone-loopback` |
| Overview | Equipment non-empty; Zone Other **tables visible**; AFDD `fdd/run` on `bldg2` |
| Evidence | BUG_REPORT verdict + report dir — or **DEFERRED** with operator-browser reason |

## Dropped as silly

- Full matrix after every OT child when tip images unchanged
- Claiming ingest healthy from `edges:1` alone while `ingest_ok` is flat
- Merging docs mid-Publish (cancels fieldbus)
- Fake Lab operational-gate sliders without SQL/session binding
- Wave G mockups backed by constants; green N/A families; Python in central/web paths; ONNX/GPU/graph DB without measured need
- Calling Wave G “production-qualified” or Guideline 14 without matched sim + measurements

## Wave loops

**Waves D / E / F (OT mid-wave):**

```text
hygiene → one-concern PR (VERSION only if images ship)
  → if images: backup → re-pin central→mqtt→web → fieldbus sha-<7>
  → Railway smoke → wave note in BUG_REPORT → hygiene
```

**Soft-OPEN closeout (required before Wave G):**

```text
final tip pinned + fieldbus up
  → ONE full run_railway_hub_stress.sh
  → cite fully_qualified + Overview MQTT gate
  → BUG_REPORT Waves D–F CLOSED → hygiene
```

**Wave G (experimental — after closeout):**

```text
inventory vs tip → short plan in BUG_REPORT/capability ledger
  → one child rev at a time (37→42), Rust+React gates green
  → synthetic/unit proof each child; smoke only if images ship
  → no Railway deploy / merge-to-prod unless separately authorized
  → handoff: limitations + disabled research claims if external labeled set missing
```

Locked OT path: Railway hub + bensbench x86 fieldbus; low-RAM; no Pi / no live OT DoS. Ops: [`PATCH_CYCLE.md`](../PATCH_CYCLE.md) · [`STRESS_CLOSEOUT.md`](../STRESS_CLOSEOUT.md).  
Wave G runtime boundary: Rust central, React web, Parquet historian, DataFusion features — see [`AGENTS.md`](../../AGENTS.md) / [`openfdd_agent_spec/AGENTS.md`](../../openfdd_agent_spec/AGENTS.md).
