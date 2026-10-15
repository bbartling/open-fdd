# Open-FDD shared SQL/schema contract

Versioned checksum ledger for **BPS ↔ OSS apples-to-apples** parity.

- Consumers (public Rust open-fdd, private BPS Python) pin `contract_version` + `pack_sha256`.
- Equations live in `sql/fdd/`, `sql/schema/`, and `sql/analytics/` — adapters bind/auth/serialize.
- Digital twin / IoT layers sit **beside** the warehouse; they must not redefine FDD SQL, schema, or rule IDs.
- Soft-OPEN ≠ FQ. Timescale ONLY — no dual-write / Parquet co-canonical.
- Successor bundle Soft-OPEN scaffold: `sql/contract/successor_bundle/` (original warehouse hash preserved).

See `manifest.json` (contract_version `3.6.14-softopen`) and
`.cursor/plans/post_wave_x_363_softopen_residuals_20261014.plan.md` § BPS↔OSS.

## C2 checksum compare (CI + Soft-OPEN vendor gate)

Canonical FDD surface is **`sql/fdd/postgres/rules` (77) + `sql/fdd/registry.yaml`**.
Do not treat legacy `sql_rules/` as the shared equation pack.

| Mode | Command | When |
| --- | --- | --- |
| Self-pin (CI) | `python3 scripts/sql_fdd_bps_checksum_compare.py` | Always — fails if tip drifts from `sql/contract/manifest.json` |
| Vendor compare | same + `--bps-root /path/to/openfdd-warehouse` or `OPENFDD_BPS_WAREHOUSE_ROOT` | Soft-OPEN agent with RO BPS mount — fails on byte equation drift |

Also invoked from `scripts/softopen_r6_harness_check.sh` step 7. Public synthetic / public OSS only in CI; private twin paths stay on the agent host.
