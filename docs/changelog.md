---
title: Changelog
nav_order: 18
---

# Changelog

## Open-FDD 5.0.16 - 2026-11-12 (open-fdd 4.5.7 on PyPI)

One shared core schema (`sql/fdd/schema/core.sql`: `fdd.point`, `fdd.rule_result`, `fdd.rule_config`). Timescale schema version 4 copies and drops `openfdd.fdd_results` / `openfdd.retention_log` (see [migrating to 5.0.16](upgrade-5x.html)). The hook loads history from the SI view `fdd.input_sample`. Input contract version 3 declares that view's signature. FDD results are unchanged unless you save tuning.

- **Sweep tuning (Full, #1589):** a Tuning tab edits the five sensor sweeps' per-role limits for a site or one equipment in display units (degF, inH2O, cfm, gpm) and stores SI revisions in `fdd.rule_config` (shipped, then site, then equipment). Every save is validated first; preview, reset and rollback keep an append-only history. The next `fdd` run applies the active revision and records it on each result row. Lite has no editor.

## Open-FDD 5.0.15 - 2026-11-11 (open-fdd 4.5.6 on PyPI)

Tidy-up. FDD results are unchanged (parity run: 71 compared, 47 matched, 24 known-divergent, 0 unexpected).

- **Breaking (contract):** SQL input contract version 2 drops the scratch tables `authorized_series` and `equipment`: no rule reads them and the hooks no longer fill them. Rule SQL is unchanged.
- **One shared source** (`shared/`, copied by `scripts/nf/sync_shared.py`, `--check` in CI) for the files Full and Lite had hand-copied, including the weather hook and a single pager. Hook ids are unchanged; the BACnet mirror is on by default in both editions and the `bacnetMirror: false` app option turns it off.
- **UI:** Full and Lite share one dashboard shell (`shared/static/app-core.js`, charts, theme). The top bar shows only the site; each tab has its own equip picker with a separate Weather entry. Every history view opens on the last 7 days. Charts: "Weather vs outside air" removed, hour-of-day heat map gets a sensor dropdown, "Other signals" shows all numeric signals with one y-axis per unit plus an on/off lane.
- **Docs:** `sql/fdd/tuning_storage.sql` is documented as the tuning storage contract, `openfdd.fdd_results` as the integration output, and the hooks and tables each edition creates are listed in one table.
- Removed a stray dev patch; moved a test-only fixture out of `hooks/lib`.

## Open-FDD 5.0.14 - 2026-11-11 (open-fdd 4.5.5 on PyPI)

- **Parity harness:** `open_fdd.parity` ships in the PyPI package: synthetic data generation (basic and `edge` profiles), a pandas reference, `Policy`/`compare`, and known differences as data. Six edge-profile input-handling differences are pinned with reasons. [#1591](https://github.com/bbartling/open-fdd/issues/1591)
- **Shared plot spec v1:** `open_fdd.plot_spec` and `nf-app/static/plot-spec.js`, a canonical preset registry, palette and units data. No UI change yet.
- **Installer:** bootstraps the NF-side schema probe on apps that predate it, adds `install --dry-run`, and `doctor` warns until the probe is installed. [#1593](https://github.com/bbartling/open-fdd/issues/1593)
- **Doctor:** explains an HTML answer from the console URL as a likely front-door URL. [#1594](https://github.com/bbartling/open-fdd/issues/1594)

## Open-FDD 5.0.13 - 2026-11-11 (open-fdd 4.5.4 on PyPI)

- **Site timezone:** range pickers and hour labels resolve the zone from the modeled site, the new `timezone` app option, or
  the NF Sites API, then the browser and UTC. A fallback is labeled (for example `UTC (fallback)`) and `doctor` warns.
  [#1584](https://github.com/bbartling/open-fdd/issues/1584)
- **Schema probe:** a read-only NF-side `schema` hook lets `doctor` and `install` check the Timescale schema without a
  database route or `psql`. [#1585](https://github.com/bbartling/open-fdd/issues/1585)
- **Doctor counts:** a stale result is counted once; fault-timeline companions are listed separately.
  [#1586](https://github.com/bbartling/open-fdd/issues/1586)
- **Timeline watermark:** tests model NF acknowledging an AddData batch that dropped a sample and show a supported
  window loses no retry. [#1574](https://github.com/bbartling/open-fdd/issues/1574)
- **Parity stress:** `tests/parity/stress.py` fails on unlisted pandas-vs-SQL divergence; TRIM-3 and VAV-REHEAT differences are root-caused and pinned. [#1582](https://github.com/bbartling/open-fdd/issues/1582)
- **Sensor sweeps:** one typed SI limit source feeds SQL and pandas sweeps; new plant roles (CHW flow and differential pressure, condenser-water temperatures, chiller kW). [#1581](https://github.com/bbartling/open-fdd/issues/1581)
- **Docs:** removed stale references to retired 4.x SQL engines.

## Open-FDD 5.0.12

- **Chart ranges:** every chart defaults to All history and supports 1 hour, 24 hours, 1 week, and a custom range.
  Range state persists and reads remain chunked. [#1577](https://github.com/bbartling/open-fdd/issues/1577)
- **Fault lanes:** hide empty leftovers from stale or excluded sensor results while keeping assessed-zero lanes visible.
  Existing NF points and history are not deleted. [#1578](https://github.com/bbartling/open-fdd/issues/1578)
- **Duration labels:** round displayed coverage and fault hours without changing stored values or comparisons.
  [#1579](https://github.com/bbartling/open-fdd/issues/1579)
- **Timescale preflight:** remote installer clients fail clearly when a loopback database address is unreachable and
  accept an explicit protected DSN override. [#1576](https://github.com/bbartling/open-fdd/issues/1576)
- **Documentation.** Publish short SQL, pandas, API, and NF app guides. Keep prompts and episode notes out of the
  Pages site. [#1580](https://github.com/bbartling/open-fdd/issues/1580)

See the full [CHANGELOG.md](https://github.com/bbartling/open-fdd/blob/master/CHANGELOG.md) and
[GitHub releases](https://github.com/bbartling/open-fdd/releases).
