# Cycle 4 — SV sensors: 5-role SQL vs pandas all-sensor sweep

Execute after [03_chw1_econ347.md](03_chw1_econ347.md). Hard DataFusion port — expect a large PR or a deliberate `sql_screening` keep. Do **not** wait for GHCR / `:nightly`.

## Hypothesis

Dump leftover: **~122 SV-RATE / STALE / FLATLINE / RANGE / SPIKE** rows — the bulk of the 212.

Pandas sweeps **all mapped sensors** on the equipment. SQL [`sql_rules/sv_stale.sql`](../../../sql_rules/sv_stale.sql) (and siblings) window only **five** analog roles: `oa_t`, `mat`, `zone_t`, `rat`, `sat`. Extra points (DP, CO2, humidity, extra zone sensors, …) fault in pandas and stay silent in SQL → pandas FAULT / SQL PASS, or hours that only count the five roles.

Liberty OFDD-065 is still **WIDE** on the catalog; do not flip `proven` from B100 hours.

This is a **definition + port** problem, not an `ELSE 1` fan-gate.

## Files a later agent may change

- [`sql_rules/sv_stale.sql`](../../../sql_rules/sv_stale.sql) and sibling `sv_*.sql`
- Ingest only if extra analogs never get roles (then SQL cannot see them even after a sweep)
- [`crates/fdd_rules/src/oracle_parity_test.rs`](../../../crates/fdd_rules/src/oracle_parity_test.rs)
- Catalog: keep `sql_screening` until fixtures prove the equation. Do **not** mark `proven` because dump hours moved.

If a full per-sensor SQL sweep is not feasible in DataFusion this cycle: document `semantic_gap` (pandas all-sensor vs SQL five-role) and **leave screening**. That is an allowed stop — do not fake 0 vs thousands of hours.

## Tests (synthetic + GHA)

Follow the [shared contract](00_INDEX.md#shared-test-contract-every-cycle).

1. **GHA two-column fixture:** one live analog **outside** the five roles (e.g. extra humidity) that is stale/flat in pandas; the five roles are healthy. Today SQL must **not** report stale on that extra point. After a real port, SQL must match pandas **tiny** hours on that point. If you keep screening, the test documents the gap (pandas FAULT / SQL PASS) and must **not** be auto-accepted in [`tests/test_wattlab_parity_diff.py`](../../../tests/test_wattlab_parity_diff.py).
2. **GHA five-role healthy:** all five roles changing → SQL no stale. Guards a false-positive sweep.
3. 6 samples × 5 min, `confirm_rows=2`. Not B100 thousands of hours.
4. Synthetic-59 **59/59**.

## Do not GHCR

Merge = squash after **Rust CI**. No nightly pin. A later soak is the only way to see dump 122 → N.

## Out of scope

- SCHED-247 (cycle 5)
- Editing vibe19 pandas so B100 matches
- Mass `ELSE 1`
- Promising 212→0
