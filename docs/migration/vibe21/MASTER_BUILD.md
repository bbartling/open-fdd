# Master build — calibrated twin → champion model → runtime bundle

Offline-only. Production images stay Python-free. See program plan and
[`PYTHON_BOUNDARY_AND_MODEL_SUPPLY_CHAIN.md`](../../tools/open-fdd-vibe21-production/PYTHON_BOUNDARY_AND_MODEL_SUPPLY_CHAIN.md).

## Stages

1. **calibrate** — import BEST G14 twin (WattLab run or oracle `assets/twin_b100_ops11`).
2. **farm** — `tools/dm_hourly_farm.py` → `dm_hourly_rows.parquet`.
3. **qc** — DataFusion/Arrow schema + day-group checks.
4. **features** — emit `feature_spec.json` / `target_spec.json` (parity with `ml/feature_compile_dm.py`).
5. **train** — sklearn family hunt (Ridge/EN/RF/ExtraTrees/GBR/HistGBR + voting/stacking);
   serialize **champion only**; write `leaderboard.json` + card; export portable ONNX/trees.
6. **map** — optional FDD `mapping_revision` under the same `job_id`.
7. **unity** — pack `flask_app/webgl/` → `unity_webgl_build.zip` + manifest hashes.
8. **bundle** — `runtime_bundle.json` pins active digests.

CLI: `scripts/vibe21_master_build.sh` (PR2b).

## Layout

```text
jobs/{job_id}/
  twins/{twin_version_id}/
  simulations/{farm_run_id}/
  datasets/{dataset_id}/
  models/{model_release_id}/   # champion portable + leaderboard
  mappings/{mapping_revision_id}.json
  unity/{unity_build_id}/
  runtime_bundle.json
```
