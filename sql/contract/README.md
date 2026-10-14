# Open-FDD shared SQL/schema contract

Versioned checksum ledger for **BPS ↔ OSS apples-to-apples** parity.

- Consumers (public Rust open-fdd, private BPS Python) pin `contract_version` + `pack_sha256`.
- Equations live in `sql/fdd/` and `sql/schema/` only — adapters bind/auth/serialize.
- Digital twin / IoT layers sit **beside** the warehouse; they must not redefine FDD SQL, schema, or rule IDs.
- Soft-OPEN ≠ FQ. Timescale ONLY — no dual-write / Parquet co-canonical.

See `manifest.json` and `.cursor/plans/post_wave_x_363_softopen_residuals_20261014.plan.md` § BPS↔OSS.
