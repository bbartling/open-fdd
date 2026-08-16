# WattLab-to-WattLab dump parity (Building 100) — vibe19 4.4.1 / `sha-726211b`

Oracle: vibe19 Engineering Bundle `ghcr.io/bbartling/vibe19:latest` digest `sha256:159802ca…f9ae52b0` (OCI revision `11cc1cdc…`), wheel **4.4.1**, catalog `2e684dbb…cba9`. Diagnostic dump includes `vav_health_matrix.csv`, `mech_cooling_oat_bins.csv`, `motor_hours.csv`, `motor_weekly.csv`. `agent_afdd` rc **0**.

OpenFDD: DataFusion on **`sha-726211b`** (docs #732 on CAST #731). Health `3.3.0+726211b0d370`. `:nightly` digest matches central `sha256:148e56d3…e0821acc`. Stack: `OPENFDD_IMAGE_TAG=sha-726211b` `react-ot --no-pull` (override sticky `.env` `sha-8ab0b5e`). No local docker/cargo build.

## Cycle header

| Metric | Value |
| --- | --- |
| Date | 2026-08-16 |
| OpenFDD pin | `sha-726211b` health `3.3.0+726211b0d370` |
| PyPI / vibe19 wheel | **open-fdd 4.4.1** |
| Vibe19 | `:latest` `sha256:159802ca…f9ae52b0` |
| **blockers** | **449** |
| accepted | 2689 |
| rows | 3303 |
| stop_rule_met | **false** |

Gate 0: PUT kept `occupancy_schedule`. Missing API: `topology.csv` on OpenFDD assembler only.

## Building 50 hourly IoT append

Zip `/home/ben/raw_BUILDING_50_openfdd.zip` (51 equipment, **2963** UTC hours in file). Low-RAM sim: seed truncated hour-0 package, then `POST /api/csv/import/package/append` for **47** following hours (`--max-hours 48`, `--sleep 0`). Driver gitignored (`reports/…/hourly_b50_append_sim.py`). Did not commit the zip.

| Check | Result |
| --- | --- |
| Seed | `building_id=BUILDING_50` ok |
| Appends | 47/47, **0** errors; parquet rows 3136 → 26656 |
| Replay hour `2026-03-16T03` | `rows_added_sum=0`, `rows_duped_sum=588`, **idempotent** |
| `POST /api/fdd/run` | ok, 2104 results, 5.2 s |
| BUILDING_100 | left in place (distinct site) |

Full 2963-hour replay would re-ingest parquet every hour; not run on this bench.

## Synthetic-59

| Side | Target match |
| --- | --- |
| vibe19 pandas | **59/59** (`agent_afdd` rc 0, not reused) |
| OpenFDD SQL | **59/59** |
| Overview analytics | **PASS** (runtime + mech OAT bins) |

## Four B100 FDD examples (`sha-726211b`)

| ID | vibe19 pandas | OpenFDD SQL | Notes |
| --- | ---: | ---: | --- |
| `AHU-DUCTHI` AHU_2 | FAULT **0.5 h** | FAULT **1.83 h** | Residual FAULT∩FAULT |
| `ECON-2` AHU_1 | PASS **0 h** | FAULT **1422.92 h** | Unchanged vs CAST soak. Historian damper ~100% in high OAT; pandas 0 h is mapping/equation, not missing dump files. |
| `ECON-1` AHU_1 | FAULT **326.08 h** | PASS **0 h** | Unchanged |
| `CHW-NOLOAD-1` CHILLER_2 | FAULT **524.5 h** | **SKIPPED_MISSING_ROLES** | No false PASS; accepted |

No Windows vibe19 prompt this cycle (dump CSVs present, 59/59, export rc 0).

## Commands

```bash
export OPENFDD_IMAGE_TAG=sha-726211b   # after sourcing .env
./scripts/openfdd_stack_up.sh react-ot --no-pull
python3 scripts/synthetic_59_target_pair_soak.py --side both --workspace /home/ben/wattlab_workspace
python3 scripts/wattlab_parity_oracle_dump.py
python3 scripts/wattlab_parity_ofdd_rust_bundle.py
python3 scripts/wattlab_parity_diff.py
```
