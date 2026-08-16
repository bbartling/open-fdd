# WattLab / Vibe19 parity — Building 100 + Synthetic-59 (`sha-69494c2`)

Dump-vs-dump after `docker pull ghcr.io/bbartling/vibe19:latest` (`sha256:159802ca…f9ae52b0`). OpenFDD JWT APIs on **`sha-69494c2`** (#734 mad_c OA-damper ranking). bensbench: GHCR pull + `--no-pull`; no local cargo/docker image build for FDD. Playground not patched on this host.

Working copy: `reports/wattlab-parity/` (gitignored). Proof pack: `reports/wattlab-parity/artifacts/econ_role_proof/`.

## Cycle header

| Side | Value |
| --- | --- |
| Date | 2026-08-16 |
| OpenFDD git/image | `69494c2` / `ghcr.io/bbartling/openfdd-*:sha-69494c2` |
| Central health | `3.3.0+69494c2195ac` |
| Vibe19 | `:latest` digest `sha256:159802ca…f9ae52b0` revision `11cc1cdc…` |
| `open_fdd.__version__` | **4.4.1** catalog `2e684dbb…cba9` |
| `dump_tables` / Prompt 2 CSVs | present; `agent_afdd` rc **0** |
| Gate 0 | PUT kept `occupancy_schedule` |
| `diff_summary.json` | **212 blockers**, 2752 accepted, 3138 rows, `stop_rule_met=false` |

## ECON (mapping, not CAST)

CAST percent gate (#731) was necessary but insufficient. B100 SQL ECON-2 **1422.92 h** came from ingest selecting **`ex_dmpr_pos_fan_enable_pct`** over **`mad_c`**. After #734: ECON-2 **0 h PASS**, ECON-1 **~327 h FAULT** (pandas 326.08 h; ≤1 h accepted).

## Synthetic-59

vibe19 **59/59**, OpenFDD SQL **59/59**, analytics soak **PASS**. No Windows handoff.

## Four-rule B100 soak

| ID | pandas | SQL | Outcome |
| --- | ---: | ---: | --- |
| AHU-DUCTHI AHU_2 | 0.5 h FAULT | 1.83 h FAULT | residual |
| ECON-2 AHU_1 | 0 h PASS | 0 h PASS | **fixed** |
| ECON-1 AHU_1 | 326.08 h FAULT | 327.08 h FAULT | accepted ≤1 h |
| CHW-NOLOAD-1 CHILLER_2 | 524.5 h FAULT | SKIPPED_MISSING_ROLES | no false PASS |

## Measured blockers (post dump-wave)

| Artifact | Blockers |
| --- | ---: |
| `fdd_findings` | 212 |
| `sensor_diurnal_24h.csv` | 0 |
| `sensor_stats_*` | 0 (zone means accepted with rationale) |
| `vav_health_matrix.csv` | 0 (pandas `?/3` accepted) |
| `rcx_preset_coverage.csv` | 0 |
