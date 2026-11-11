---
title: Changelog
nav_order: 18
---

# Changelog

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
- **Docs:** removed stale DuckDB/DataFusion references.

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
