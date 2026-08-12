# WattLab-to-WattLab dump parity (Building 100)

Oracle is playground Vibe19 Engineering Bundle (`openfdd_engineering_bundle_v1`).
OpenFDD side is a **DataFusion assembler** (`scripts/wattlab_parity_ofdd_rust_bundle.py`) — not pandas `tools/wattlab_export`.

## Baseline (pre-image, capture `sha-2ce9c21`)

| Metric | Value |
| --- | --- |
| `diff_matrix.csv` rows | 3803 |
| **blockers** | **3527** |
| accepted | 153 |
| stop_rule_met | false |

This is the honest dump-vs-dump stop rule. The prior cycle’s `blocker_count=0` was a sql_screening **rollup**. FAULT∩FAULT hour gaps are blockers again.

Largest FDD families in the matrix: AHU-DUCTHI / AHU-SATDEV / ECON-* / FC* / SV-FLATLINE / SV-STALE (N/A vs PASS on wrong equipment + hour deltas on AHUs).

Accepted only: CHW-1 skip/off, SCHED-247 pressure-not-fault, FC7 concept_only, rust `weather`/`unknown` extra equipment, SQL-only analytics ids vs pandas findings.

## Code landed this wave (needs GHCR `:nightly` to soak)

- Per-row `wattlab_parity_diff.py` + `diff_matrix.csv`
- Rust bundle assembler (same filenames as Vibe19)
- `equipment_kinds` on registry + `NOT_APPLICABLE_EQUIPMENT_TYPE` in `/api/fdd/results`
- Ranked `fan_status` > `fan_cmd` on AHU/ECON/FC/OA/DMP/VLV/TRIM-1 SQL
- FC2 mix_tol no longer cancels (`mat+tol < min(rat,oat)-tol`)
- CHW-2/3/4 hydronic proof CTE
- SV-STALE no longer filters fan_cmd (pandas `always`)
- Vibe19 `topology.csv` now gets `vav_to_ahu` + `parent_ahu`

## After tip image

Pull `ghcr.io/bbartling/openfdd-central:nightly` (no local docker build). Re-run:

```bash
python scripts/wattlab_parity_ofdd_rust_bundle.py
python scripts/wattlab_parity_diff.py
```

Stop rule: `blocker_count == 0`. Promote `parity_status` to `duration_parity` per rule when FAULT∩FAULT hours match ±0.05 h / 0.1%.

Runtime: `open_fdd.__version__ == 4.3.0` (no PyPI bump; SQL ships in the image).
