# WattLab / Vibe19 parity — Building 100 + Synthetic-59 + B50 append (4.4.1 / `sha-726211b`)

Dump-vs-dump after `docker pull ghcr.io/bbartling/vibe19:latest` (`sha256:159802ca…f9ae52b0`). OpenFDD JWT APIs on **`sha-726211b`**. bensbench: pull only, `--no-pull`, no local docker/cargo. Playground not patched on this host.

Working copy: `reports/wattlab-parity/` (gitignored).

## Cycle header

| Side | Value |
| --- | --- |
| Date | 2026-08-16 |
| OpenFDD git/image | `726211b` / `ghcr.io/bbartling/openfdd-*:sha-726211b` |
| Central health | `3.3.0+726211b0d370` |
| Vibe19 | `:latest` digest `sha256:159802ca…f9ae52b0` revision `11cc1cdc…` |
| `open_fdd.__version__` | **4.4.1** catalog `2e684dbb…cba9` |
| `dump_tables` / Prompt 2 CSVs | present; `agent_afdd` rc **0** |
| Gate 0 | PUT kept `occupancy_schedule` |
| `diff_summary.json` | **449 blockers**, 2689 accepted, 3303 rows, `stop_rule_met=false` |

## Synthetic-59

vibe19 **59/59**, OpenFDD SQL **59/59**, analytics soak **PASS**. No Windows handoff.

## Building 50 hourly append

Seed hour-0 truncated package + 47 hourly `package/append` POSTs (51 equipment). Replay idempotent (`rows_added=0`). FDD run ok. Zip has 2963 hours; this soak used 48 for RAM.

## Four-rule B100 soak

| ID | pandas | SQL | Outcome |
| --- | ---: | ---: | --- |
| AHU-DUCTHI AHU_2 | 0.5 h FAULT | 1.83 h FAULT | residual |
| ECON-2 AHU_1 | 0 h PASS | 1422.92 h FAULT | mapping gap, not vibe19 export |
| ECON-1 AHU_1 | 326.08 h FAULT | 0 h PASS | mapping gap |
| CHW-NOLOAD-1 CHILLER_2 | 524.5 h FAULT | SKIPPED_MISSING_ROLES | no false PASS |

## Measured blockers

| Artifact | Blockers |
| --- | ---: |
| `fdd_findings` | 217 |
| `sensor_diurnal_24h.csv` | 89 |
| `sensor_stats_fan_off.csv` | 74 |
| `vav_health_matrix.csv` | 44 |
| `sensor_stats_all.csv` | 21 |
| `sensor_stats_fan_on.csv` | 3 |
| `rcx_preset_coverage.csv` | 1 |
