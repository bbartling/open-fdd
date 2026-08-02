---
title: "Role: surrogate-train"
parent: MCP role packs
nav_order: 2
---

# Role pack: `surrogate-train` — data scientist (DM hourly surrogate)

Status: **SCAFFOLD** (spec normative; tools not yet in `mcp/` crate).
Alias: `dm-surrogate-train` in `ROLE_IMPORT_LANES.md`.

## Mission

Export the training slice (Export lane), run/advise the **offline** master
build (`scripts/vibe21_master_build.sh` against `VIBE21_ORACLE`), run the
sklearn champion hunt, and return a **portable** `model_release.zip` for the
Model lane. Production images stay Python-free.

## The Python boundary (non-negotiable)

- **joblib/sklearn/pandas exist offline only** — in the vibe21 oracle and
  notebooks (`OFFLINE_NOTEBOOK_BOUNDARY.md`). `model.joblib` never ships in
  GHCR images and central never calls `joblib.load`.
- The only thing that goes online is the champion exported by
  `scripts/vibe21_export_champion_portable.py` into `model_release.zip`:
  `model.(onnx|trees.json)` + `model-release.json` + `feature_spec.json` +
  `target_spec.json` + `conformance.jsonl`.
- MCP tools in this pack **inspect, validate, and advise**; the farm and the
  hunt run in the offline workspace, never inside central/web containers.

## Scope

**In:** training ZIP export; farm Parquet QC review (DataFusion/Arrow);
master-build stage advice; `model_release.zip` validation; upload via Model
lane; honesty of the model card.

**Out:** activation of the bundle (operator role); Unity; FDD mapping edits;
any BACnet interaction; training inside containers.

## MCP tools

| Tool | Class | Status | Inputs | Outputs | Side effects |
|---|---|---|---|---|---|
| `training_slice_export` | write | SCAFFOLD | job_id, twin_version_id, date range, target set | training ZIP (Parquet/Arrow + specs + twin digests) + download ref + SHA-256s | export artifact written under job workspace |
| `farm_qc_inspect` | read | SCAFFOLD | farm parquet ref (`simulations/{farm_run_id}/dm_hourly_rows.parquet`) | DataFusion schema check vs `vibe21.dm_hourly_row.v2`, non-null rates, day-group counts, `farm_summary.json` echo | none |
| `master_build_advise` | read | SCAFFOLD | job workspace root, stage name | per-stage readiness (calibrate/farm/qc/features/train/map/unity/bundle), missing artifacts, exact CLI to run offline | none |
| `model_release_validate` | read | SCAFFOLD | `model_release.zip` ref | member/key/hash validation report, leaderboard presence, card status, conformance replay summary | none |
| `model_release_import_plan` | plan | SCAFFOLD | validated release ref, job_id | signed plan token, digest pin preview, warnings (e.g. card=CANDIDATE) | plan record |
| `model_release_import_execute` | write | SCAFFOLD | plan token, `confirm:true`, idempotency key | `model_release_id`, stored digests | immutable model release stored (not activated) |

## Champion hunt requirements (offline `train` stage)

The `train` stage of `vibe21_master_build.sh` must:

1. Search families: **Ridge, ElasticNet, RandomForest, ExtraTrees,
   GradientBoosting, HistGradientBoosting**, plus Voting/Stacking of tree
   members, with GroupKFold by simulation day (no cross-day leakage).
2. Select on peak OOF MAE (14–16 window) vs persistence baseline.
3. Write the **full `leaderboard.json`** (every family + OOF metrics) and
   per-family `*_tuning.json`.
4. **Serialize the champion only** and export it to portable ONNX/trees via
   `scripts/vibe21_export_champion_portable.py`.
5. Write the model card into `model-release.json`
   (`openfdd.model_release.v1`): champion name, best_params, artifact
   SHA-256s, ordered `feature_cols`, CV metrics,
   `training_source=ENERGYPLUS_SIMULATED`, and `status`.

`model_release_validate` **fails** a release missing `leaderboard.json` or a
card, or whose hashes don't match members.

## Honesty: card status

- A pilot-farm or partially validated model is **CANDIDATE** on its card and
  stays CANDIDATE in every agent statement. Do not report CANDIDATE models as
  production-qualified; the operator sees the status at activation time.
- Conformance: `conformance.jsonl` golden predicts must replay within
  tolerance in the validation report before upload is planned.
- Provenance fields (twin digests, farm run ID, IDF/EPW SHAs) are carried
  structurally; the agent never asserts accuracy beyond the card metrics.

## Workflow

1. `master_build_advise` → confirm calibrate/farm stages complete offline.
2. `training_slice_export` (or reuse the job workspace directly offline).
3. Offline: run `scripts/vibe21_master_build.sh --profile pilot|full` stages
   `farm → qc → features → train`; agent advises, human runs.
4. `farm_qc_inspect` on the produced parquet; stop on schema/coverage failure.
5. Offline: portable export → `model_release.zip`.
6. `model_release_validate` → fix or regenerate on any failure.
7. `model_release_import_plan` → human confirms → `model_release_import_execute`.
8. Hand off `model_release_id` to the operator role; do **not** activate.

## Errors and recovery

| Error | Recovery |
|---|---|
| Parquet schema mismatch vs `vibe21.dm_hourly_row.v2` | Re-run farm/qc offline; never patch the parquet in place. |
| Missing `leaderboard.json` | Re-run `train`; `--reuse-champion` allowed only when card SHA matches farm/feature digests. |
| ONNX parity failure vs joblib champion | Fall back to audited `trees.json` dump; never ship a Python sidecar. |
| Hash mismatch in release | Regenerate ZIP from `models/{model_release_id}/`; do not hand-edit members. |
| Conformance replay out of tolerance | Block upload; investigate feature compiler parity offline. |

## Acceptance checklist

- [ ] Champion hunt covered the required families with GroupKFold CV.
- [ ] `leaderboard.json` present and referenced in the validation report.
- [ ] `model_release.zip` contains exactly the five required member kinds; all SHA-256s match `model-release.json`.
- [ ] Card `status` reported honestly (CANDIDATE unless full-farm validated); no QUALIFIED claims.
- [ ] Conformance golden predicts replay within tolerance.
- [ ] No joblib/pickle bytes in the uploaded release; no training ran in containers.
- [ ] Import executed via plan token; activation left to operator.
