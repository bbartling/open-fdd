# WattLab-to-WattLab dump parity (Building 100) — 4.4.0 cycle

Oracle: vibe19 Engineering Bundle (`ghcr.io/bbartling/vibe19:latest`, wheel **4.4.0**).  
OpenFDD: DataFusion assembler [`scripts/wattlab_parity_ofdd_rust_bundle.py`](../../scripts/wattlab_parity_ofdd_rust_bundle.py) on `sha-9e280ae`.

## Cycle header

| Metric | Value |
| --- | --- |
| Date | 2026-08-15 |
| OpenFDD pin | `sha-9e280ae` health `3.3.0+9e280ae294b0` |
| Vibe19 | `:latest` == `:develop` digest `sha256:6a4297b9…e6f54d` rev `8ca6a3b` |
| `diff_matrix.csv` / summary rows | 4233 |
| **blockers** | **2596** |
| accepted | 63 |
| stop_rule_met | **false** |

Stop rule remains `blocker_count == 0`. FAULT∩FAULT hour gaps are blockers.

Program A (this cycle) patches SQL for AHU-DUCTHI / ECON-1 / ECON-2 / CHW-NOLOAD-1 and treats N/A-omit plus one-sided sensor columns as **accepted**. Re-count blockers after `sha-<7>` retarget. Stop rule remains `blocker_count == 0`.

Largest FDD class previously: vibe19 `NOT_APPLICABLE_EQUIPMENT_TYPE` rows omitted by Rust (750) plus skip-vs-PASS. Those are no longer dump blockers. Remaining blockers should be FAULT vs PASS and FAULT∩FAULT hour gaps.

Vibe19 diagnostic dump did **not** emit `vav_health_matrix.csv`; OpenFDD did. That is export lag on vibe19 (Prompt 2), not a 4.3.0 pin — the image already imports 4.4.0 / `vav_health_matrix_v1`.

## Commands

```bash
python3 scripts/wattlab_parity_oracle_dump.py
OPENFDD_ADMIN_PASSWORD=… python3 scripts/wattlab_parity_ofdd_rust_bundle.py
python3 scripts/wattlab_parity_diff.py
```

No local `docker build`. Pin `OPENFDD_IMAGE_TAG=sha-9e280ae`.
