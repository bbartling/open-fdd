# Open-FDD shared SQL/schema contract

Versioned checksum ledger for **BPS ↔ OSS apples-to-apples** parity.

- Consumers (public Rust open-fdd, private BPS Python) pin `contract_version` + `pack_sha256`.
- Equations live in `sql/fdd/`, `sql/schema/`, and `sql/analytics/` — adapters bind/auth/serialize.
- Digital twin / IoT layers sit **beside** the warehouse; they must not redefine FDD SQL, schema, or rule IDs.
- Timescale ONLY — no dual-write / Parquet co-canonical.
- Successor bundle scaffold: `sql/contract/successor_bundle/` (original warehouse hash preserved).

## Metric / units (#1284)

| File | Role |
| --- | --- |
| [`metric_units.json`](metric_units.json) | Quantity registry; processing ABI **`metric-c-v2`** (contract); running SQL still imperial until W4/W2b |
| [`parameter_si_rename_map.json`](parameter_si_rename_map.json) | Published SI parameter renames (registry keys unchanged until W2c) |
| [`goldens/unit_vectors.json`](goldens/unit_vectors.json) | 20°C=68°F, Δ°F scale-only, percent/fraction, FCU deadband |

Admit path converts known source units into the **active pack ABI** before SQL.
Display preference must not use ±32 on deltas. Percent vs fraction is declared metadata.

See `manifest.json` and issue [#1284](https://github.com/bbartling/open-fdd/issues/1284).

## C2 checksum compare (CI + Soft-OPEN vendor gate)

Canonical FDD surface is **`sql/fdd/postgres/rules` (77) + `sql/fdd/registry.yaml`**.
Do not treat legacy `sql_rules/` as the shared equation pack.

| Mode | Command | When |
| --- | --- | --- |
| Self-pin (CI) | `python3 scripts/sql_fdd_bps_checksum_compare.py` | Always — fails if tip drifts from `sql/contract/manifest.json` |
| Vendor compare | same + `--bps-root /path/to/openfdd-warehouse` or `OPENFDD_BPS_WAREHOUSE_ROOT` | Soft-OPEN agent with RO BPS mount — fails on byte equation drift |

Also invoked from `scripts/softopen_r6_harness_check.sh` step 7. Public synthetic / public OSS only in CI; private twin paths stay on the agent host.
