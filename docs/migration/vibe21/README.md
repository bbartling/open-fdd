# Vibe 21 → Open-FDD migration notes

Pinned oracle: `/home/ben/py-bacnet-stacks-playground/vibe_code_apps_21` (see
[`BLOCKERS.md`](../../tools/open-fdd-vibe21-production/BLOCKERS.md)).

| Artifact | Path |
| --- | --- |
| Inventory | [`ORACLE_INVENTORY.json`](ORACLE_INVENTORY.json) |
| Golden predicts (joblib offline) | [`GOLDEN_PREDICTS.jsonl`](GOLDEN_PREDICTS.jsonl) |
| Master build graph | [`MASTER_BUILD.md`](MASTER_BUILD.md) |

`GOLDEN_PREDICTS.jsonl` is a **knob grid** (strategy × oat × rh × hour) regenerated offline
via `scripts/vibe21_regen_golden_grid.py`. Export copies it to the job model dir as
`conformance.jsonl` for Rust `/api/v1/predict` nearest-neighbor matching.

Unity WebGL ZIP (lab workspace, not git): `workspace/vibe21_artifacts/unity/unity_webgl_build.zip`.
