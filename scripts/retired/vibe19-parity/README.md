# Retired vibe19 / B100 dual-parity scripts

Vibe19 is **officially retired**. OpenFDD parity testing is now:

1. **Synthetic-59 golden** — `scripts/synthetic_59_*.py` against `OPENFDD_SYNTHETIC_59_RULE_WEEK_V1`
2. **Cookbook SQL oracle** — `scripts/sql_pandas_oracle_check.py` + `golden_dual_compare.py` (CI)
3. **E+ dump and clustering** — `scripts/eplus_dump_clustering_export.py` + `scripts/agent_eplus_dump.sh`

## Moved here (do not run)

| Script | Replacement |
|--------|-------------|
| `wattlab_parity_oracle_dump.py` | synthetic-59 soaks only |
| `wattlab_parity_ofdd_rust_capture.py` | `agent_eplus_dump.sh` or central APIs |
| `wattlab_parity_ofdd_rust_bundle.py` | dump zip + `eplus_dump_clustering_export.py` |
| `materialize_b100_sql_parity_fixtures.py` | synthetic fixture under `reports/*/fixtures/synthetic_59/` |
| `materialize_vav_oracle_fixtures.py` | synthetic VAV cases in synthetic-59 package |

## Still active (not retired)

- `eplus_parity_compare.py` — compare helpers for tests (was `wattlab_parity_diff.py`)
- `ghcr_watch_central.py` — GHCR publish poll (was `wattlab_parity_watch_ghcr.py`)
- `sql_pandas_oracle_check.py`, `golden_dual_compare.py` — cookbook parity CI
- `tools/wattlab_export/` — Python dump engine (central shells it; rename pending)

## Artifact paths

Prefer `reports/eplus-dump/` (`EPLUS_DUMP_ROOT`). Legacy `reports/wattlab-parity/` still works via `scripts/eplus_paths.py`.
