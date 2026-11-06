---
title: Migration status
parent: Architecture
nav_order: 3
---

# NF plugin migration: status and findings

Living notes per slice (plan: [PLAN.md](PLAN.html), decision: [ADR-014](../../architecture/adr-014-open-fdd-as-nf-plugin.html)).
Pre-plugin release pinned as git tag `v4.0.11-central`.

## Slice 3: FDD engine (edge-lite + full)

**Shape.** `nf-app/hooks/fdd.js` is one scheduled hook (hourly at :07, no point bindings). Per run, for every
Haystack equip in NF's model layer:

1. Bind rule roles with `static/fdd.js`, the exact code the FDD tab runs. The hook loads `model.js` and `fdd.js`
   unchanged in a `vm` sandbox, so the UI and the hook can't disagree.
2. Read the bound points' history from NF, resampled by NF to the pack's grid:
   `GET /api/v1/point/data?uuids=…&window=300s&method=AVERAGE`, trailing `windowHours` (default 24).
   Timestamps with no data at all are left out (a gap, not zeros), so the pack's `MAX_GAP_HOURS` logic applies.
3. Run every runnable rule of the SQL pack in an embedded engine (`hooks/lib/engines.js`):
   - **sqlite** (`sql.js`, SQLite-WASM) for small edges. The pack is translated from Postgres by
     `scripts/nf/build_sql_pack.py` and checked against PGlite for parity.
   - **pglite** (`@electric-sql/pglite`, real Postgres in WASM): the pack as written.
   - `engine: "auto"` picks pglite when NF reports ≥ 3.5 GiB RAM.
4. Write one result point per (equip, rule), with a deterministic uuid (`sha1("open-fdd:<equip>:<rule>")`, v5 layout):
   - an `automation`-layer record (`application_id=open-fdd`, `type=fdd-result`), which holds the history;
   - a `model`-layer record with Haystack tags `point,his,fault|metric,fdd`, `ruleRef`, `equipRef`, `siteRef`,
     `unit`, `dis`.
   - The value trended each run is the fault % of covered time over the window (fault rules), or the rule's first
     output column (metric rules).

The result points show up in the default layer like any other point. The dashboard, the RDF export (slice 6) and
other NF apps read them by tags.

**Memory, measured 2026-11-05 on the dev PC (Node 24).**

| engine | RSS after init | 1 equip × 7 d × 74 rules | 10 equips × 7 d |
|---|---|---|---|
| pglite 0.5.15 | ~310 MB (WASM floor 128 MB, ~240 MB external) | 1.4–1.7 s, ~350 MB | 12.9 s, ~415 MB |

A Pi 3 (1 GB) running NF has ~200–250 MB available, so pglite cannot run there; that is why sqlite exists.

| engine (dev PC, synthetic, all 77 rules) | peak RSS | time |
|---|---|---|
| sqlite (sql.js 1.15.2), 1 equip × 7 d | ~99 MB (~61 MB over the Node baseline) | 1.7 s |
| sqlite, 2 equips × 7 d | ~145 MB | 3.8 s |
| pglite 0.5.15, 1 equip × 7 d | ~367 MB | 3.8 s |

**Parity:** all 77 rules give the same rows on both engines (synthetic 2 equips × 3 d with a data gap, 1e-6 relative; 43
rules trip faults). There are no per-rule overrides; the sqlite pack's `notes` list the two approximations (windowed
STDDEV for VAV-7, and literal NaN in SV-RANGE, which NF's JSON never carries). On live bosspi data (24 h) both engines
gave identical values for all 21 runnable rules.

**On bosspi (2026-11-05):** hook run = sqlite, 21 rules, 0 errors, 21 result points written in ~5 s. sql.js is vendored
in `hooks/vendor/sql.js` (no `npm install` on the box; pglite installs only where `install_dependencies` is run).
Cost: NF starts one `applications-sdk` runtime per app with hooks. Open-FDD's sits at ~130 MB RSS right after a run;
available memory went 243 → ~140 MB, and idle pages swap to zram between hourly runs. Stable, but it is most of the
Pi's headroom. A Pi 4/5 or any ≥ 2 GB box is the realistic edge-lite floor.

**Pack bugs found:** `input_contract.sql` lacks the `ra_h`, `zone_rh`, `ma_h` and `sa_h` columns that the SV rules read,
and has no `authorized_series` / `equipment` tables. `tuning_catalog.json` `output_columns` is incomplete for 74 rules.
`build_sql_pack.py` works around both (the contract is extended, and output columns come from the SQL itself);
`sql/fdd` itself is unchanged.

**Pack fixes found on the way.** `sql/fdd/render_rule.py` didn't compute OAT-METEO's `WEB_ASOF_BOUND_SECONDS`
(cadence + margin, as central did). Fixed; all 77 rules render at defaults.

## Slice 4: FDD + RCx UI (done)

- **FDD tab:** Faults panel (latest per rule/equip + 7-day hourly heatmap), click any rule → per-rule plot
  (inputs stacked by unit family + bottom fault lane), "Run FDD now" (NF StartHook).
- **RCx tab:** 60 views from four modules (`fdd-plots.js`, `rcx-overview.js`, `rcx-presets.js`, `energy.js`)
  on one registry (`rcx.js`). Every chart of the old central UI is mapped in `nf-app/rcx-parity.json`, and
  `tests/parity.test.mjs` fails CI if one goes missing. Only utility-bill/tariff inputs are not ported (NF has none).
- **Faults:** always a stand-alone 0/1 lane at the bottom of the plot (`rcxWithFaultLane`), from the FDD hook's
  hourly result points; 11 views carry rule lanes, the per-rule plot carries any rule's lane.
- **Tested on Windows** against `nf-app/dev/mock-nf.mjs` (two sites, AHUs, VAVs, chiller/tower, boiler, meters,
  faults): all tabs render with no console errors; 63 RCx cards draw, views without usable inputs move to the
  "Not available here" list with the reason.

## Slice 5: full profile on NF TimescaleDB, blocked on schema

NF docs (docs.normal.dev/timescale) say the connector creates `instances`, `points` and `data` tables plus one view
per layer (e.g. `layer_hpl_bacnet_1`). The only columns shown are in the examples: `data(point_id, time, value)` and
`points(id, name)`. There is no DDL, no value typing and no attribute storage.

The NF 3.10.9-1 console on the bench has no Timescale settings page (checked the console bundle), so the schema
can't be observed there. What works today without Timescale: a ≥ 4 GB box gets the exact Postgres pack through
pglite, on NF's own history.

Next step, needs a decision: a Timescale-enabled NF (enterprise build or NF engineering) to read the real DDL. Then
`fdd.js` gets a `source: "timescale"` path that builds `history` with SQL straight from `data` and the layer views,
and runs the pack inside TimescaleDB itself, with no WASM.
