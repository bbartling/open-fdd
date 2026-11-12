---
title: Parity harness
parent: Rules
nav_order: 5
---

# Parity harness

The parity harness is a versioned part of the `open-fdd` package (`open_fdd.parity`). Any app that runs the Open-FDD rule SQL on its own
database can use it to prove that the SQL result equals the pandas reference on the same data. It is stdlib plus
pandas: `pip install open-fdd[oracle]` is all a third-party adapter needs. All values are SI.

Older PyPI releases (4.5.4 and earlier) do not include it: install from git until a later release is published,
`pip install "open-fdd[oracle] @ git+https://github.com/bbartling/open-fdd"`.

```python
from open_fdd.parity import generate, reference, compare, Policy, run_adapter

ds = generate(seed=0, equips=8, days=7, profile="basic")   # SI samples + Haystack model + role map
ref = reference(ds)                                        # pandas results (needs pandas)
rows = run_adapter(MyAdapter(), ds)                        # your engine runs the pack SQL on ds
verdict = compare(rows, ref, Policy.default())
print(verdict.summary())      # parity: compared=71 matched=47 known-divergent=24 unexpected=0 -> OK
assert verdict.ok
```

## API

| Call | What it does |
|---|---|
| `generate(seed, equips, days, profile="basic")` | Returns a `Dataset`: `history` (wide engine-input rows), `samples()` (long format `(equipment_id, column, ts_ms, value)`), `weather`, `model` (site, equipment, points with role, scale and unit), `role_map`, `faults` (planted windows), `to_engine_input()`, `content_hash()`. |
| `reference(dataset)` | Runs the pandas twin of every SQL rule and returns `{rule_id: {equipment_id: {"pandas": hours, "status": ...}}}`. |
| `Policy.default(profile, stress)` | Tolerance (`abs_tol_h` 1e-6 h; per-sensor sweeps 0.0005 h plus 1e-6 relative), fail-on-zero-compared, fail-on-short-comparison, and the shipped known-difference list for the chosen scopes. |
| `compare(sql_rows, ref_rows, policy)` | Returns a `Verdict` (`ok`, `compared`, `matched`, `known_divergent`, `unexpected_rules`, `summary()`). |
| `known_differences(*scopes)` | `{rule: reason}` from `open_fdd/data/parity_known_differences.json`; scope is `all`, `stress_only` or `edge`. |
| `to_imperial(ds)` / `from_imperial(ds)` | SI to degF, inH2O, CFM and percent (and back, exact within 1e-9). |
| `published_hashes()` | The content hashes shipped with this version. |

`sql_rows` is `{rule_id: [row, ...]}` in the contract shape: the rule's output columns from
`sql/fdd/tuning_catalog.json` (`equipment_id` and `fault_hours`; the per-sensor sweep rules also return `series_id`,
`sensor_role` and `covered_hours`). A rule is compared when the reference has a twin and the engine returned a non-null
`fault_hours`.

## Profiles

- `basic`: the dataset the in-repo suite has always used (a healthy unit, a sick unit with fault windows, a 5-minute
  grid, Monday 2026-01-05 00:00 UTC). It is a bit-exact port of `nf-app/tests/fixtures/synthetic_dataset.js`; the repo test
  `tests/parity/test_generator_equivalence.py` runs both generators and asserts identical rows, which keeps the
  known-difference list valid. Seed 0 is that data. Other seeds salt the column hash and shift the start by whole weeks.
- `edge`: `basic` plus, deterministically from the seed: null runs, a 3 hour gap on every even unit, timestamp jitter of
  +-60 s, duplicate rows, out-of-order rows, a DST-transition week (America/Chicago, timestamps stay UTC; occupancy
  follows local time; starts Friday 2026-03-06 so a run of 3 or more days crosses the 2026-03-08 change), and planted
  faults (a `sat` flatline and a `zone_t` out-of-range block per unit) whose nominal windows are in `dataset.faults`.

The `edge` profile exposes six input-handling differences between the SQL pack and the pandas reference that the
`basic` data never reaches (series that starts with the fan running, NULL runs, out-of-range values, a long gap,
duplicate rows). They are listed with the reason and evidence in `parity_known_differences.json` under scope `edge`;
`Policy.default("edge")` includes them. `generate(..., edge_features=[...])` enables a subset of the stresses
(`nulls`, `planted`, `gap`, `jitter`, `duplicates`, `out_of_order`) to bisect a divergence.

`reference(ds)` sorts rows by time and drops duplicate timestamps before running the pandas rules (a no-op on `basic`);
pass `ingest="as_is"` to see the raw behavior.

## Hash stability

`dataset.content_hash()` is the sha256 of a canonical serialization (sorted keys, compact, floats by repr, `-0.0` as
`0.0`; `sensor_history` is derived and not hashed). For a given `(profile, seed, equips, days)` it is stable for a given
package version, and it only changes when `GENERATOR_VERSION` is bumped (changelog entry required). The sine function is
a pure-Python port of the fdlibm `sin` JavaScript engines use, so the hash does not depend on the platform's libm.
`open_fdd/data/parity_hashes.json` publishes the hashes for 2x3 and 8x7 on both profiles; a test pins them.

## Adapter interface

An adapter implements three methods (`open_fdd.parity.EngineAdapter`): `load(dataset)`, `run(rule_ids) -> rows`,
`close()`.

```python
class SqliteAdapter:
    name = "my-sqlite"

    def load(self, dataset):
        self.db = sqlite3.connect(":memory:")
        data = dataset.to_engine_input()          # history, weather, authorizedSeries, sensorHistory, equipment, ...
        create_tables_and_insert(self.db, data)   # your ingest; ts is epoch milliseconds, values are SI

    def run(self, rule_ids=None):
        ids = rule_ids or ALL_RULE_IDS
        return {rid: [dict(r) for r in self.db.execute(rule_sql(rid))] for rid in ids}

    def close(self):
        self.db.close()

assert conformance_errors(SqliteAdapter(), generate(0, 2, 1), ["FC1"]) == []
```

The in-repo adapters (`tests/parity/adapters.py`) run the pack on PGlite and sql.js through `nf-app/hooks/lib/engines.js`.

## How a downstream app uses it

1. Add `open-fdd[oracle]` to the test dependencies.
2. Write an adapter for your database (or your ingest plus the rendered pack SQL).
3. In CI: `generate` both profiles, `run_adapter`, `reference`, `compare`; fail the build on `not verdict.ok`.
4. To test unit handling at ingest, push `to_imperial(ds)` through your ingest and expect the same verdict as the SI run.
5. Differences you cannot fix go in your own `Policy(known={...})`, with a reason, not in a silent tolerance.

From the repo: `python tests/parity/stress.py --equips 8 --days 7 [--profile edge]`.
