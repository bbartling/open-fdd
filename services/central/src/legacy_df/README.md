# Legacy DataFusion / Parquet (Wave-X quarantine)

Product default build: Timescale-only (`OPENFDD_DATABASE_URL` / `OPENFDD_HISTORIAN=timescale`).

- `analytics/historian.rs` still contains DF SQL over Parquet for **pre-3.6 bring-up** and for
  code paths not yet ported; runtime fail-closed when Timescale is active
  (`new_bounded_session` bails; `cached_analytics!` never calls DF).
- Enable Cargo features `legacy-datafusion` / `legacy-parquet` only for bring-up tests.
- Archive mirror: `analytics/historian_datafusion.rs` (same body as historian.rs until full delete).
- Remaining SessionContext hits in `fdd_sql` + `edge` are **BLOCKED** for compile-out until
  edge FDD registry is ported off DF (Soft-OPEN ≠ FQ).
