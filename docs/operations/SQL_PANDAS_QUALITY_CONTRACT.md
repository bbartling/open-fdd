# SQL ↔ pandas quality contract (#1253)

Soft-OPEN evidence. Soft-OPEN ≠ FQ.

## Finding

On live plant-pack history (BPS Building 50 / `AHU_1`), **AHU-SATDEV** warehouse
SQL fault hours matched a pandas oracle with `quality=False` exactly. The gap vs
full `open_fdd.rules.run_rule` (`quality=True`) was fully explained by
`open_fdd.quality` nulling `OUT_OF_RANGE` / sentinel samples — **not** by
SAT_DEV_ERR, fan-gate, or confirm equation drift.

## Contract (Soft-OPEN)

| Surface | Quality (`OUT_OF_RANGE` / sentinels) | Contractual for warehouse SQL? |
| --- | --- | --- |
| Timescale / warehouse SQL (`sql/fdd/**`) | **OFF** (raw historian values; SQL has no quality filter) | **Yes — product FDD** |
| Pandas SQL-aligned oracle (equation + gate + confirm, `quality=False`) | **OFF** | **Yes — SQL parity oracle** |
| Full `open_fdd.rules.run_rule` (`quality=True`) | **ON** | **No** — separate surface; hour deltas vs SQL are DIAG only |

## Fail-closed enforcement

- Unit CI: `tests/rules/test_sql_quality_contract.py`
- Live stress: `scripts/stress/08_sql_vs_pandas_sparql.py` — strict SQL ≈ quality-OFF;
  `--allow-satdev-drift` is WARN-only lab emergency (do not weaken default).

Pandas DataFrames for cookbook rules must use **Haystack role column names**
(`discharge-air-temp`, `discharge-air-temp-sp`, `fan-status`, …). Warehouse short
aliases (`sat` / `sat_sp`) are SQL-only and must not silently green pandas parity.

## Longer-term (out of Soft-OPEN)

Port role-aware OUT_OF_RANGE / sentinel filtering into warehouse SQL (or an ingest
quality channel) if product SQL hours should match the default pandas runner on
dirty plant packs. Until then, keep the two surfaces explicit.
