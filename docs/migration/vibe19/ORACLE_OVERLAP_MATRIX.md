# Vibe19 ↔ Open-FDD output overlap matrix (Phase 1)

Vibe19 SHA reference: `5006a16f2c7729145e9765e719f72d816489f5ee`  
Oracle artifacts: `tests/fixtures/vibe19_analytics_golden/` (small fixture) and local `.cache/oracle_b100/` (Building 100 export; not committed).

| Open-FDD output | Vibe19 output | Comparison type | Status |
| --- | --- | --- | --- |
| Rule result `fault_hours` / `status` (FC1–3,8–13, ECON-1/2/4, VAV-1, OAT-METEO, rollups) | `rule_digest.csv` | exact_direct_equivalent | parity CLI compares |
| Other registry FDD rules | `rule_digest.csv` rows when present | equivalent_after_normalization | compared when both emit |
| `PID-HUNT-1` | — | openfdd_only | excluded from gate |
| `motor_hours` analytics | `motor_hours.csv` | analytics_rollup | **parity-proven** vs small golden (`analytics::motor_hours_matches_vibe19_small_golden`) |
| `motor_weekly` | `motor_weekly.csv` | analytics_rollup | pending |
| `mech_cooling_oat_bins` | `mech_cooling_oat_bins.csv` | analytics_rollup | pending |
| `rcx_preset_coverage` | `rcx_preset_coverage.csv` | analytics_rollup | pending |
| `rcx_preset_digests` | `rcx_preset_digests.csv` | analytics_rollup | pending |
| Six-status OFF / N/A | Vibe19 status column | equivalent_after_normalization | Open-FDD emits richer statuses |

## Command

```bash
cargo run -p fdd_cli --release -- parity \
  --oracle-dir .cache/oracle_b100 \
  --sql-results .cache/rule_results_b100_status \
  --output .cache/parity/b100 \
  --tolerance 0.5 \
  --openfdd-sha "$(git rev-parse HEAD)" \
  --vibe19-sha 5006a16f2c7729145e9765e719f72d816489f5ee
```
