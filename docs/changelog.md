---
title: Changelog
nav_order: 18
---

# Changelog

## Open-FDD 5.0.12

- **Chart ranges:** every chart defaults to All history and supports 1 hour, 24 hours, 1 week, and a custom range.
  Range state persists; reads remain chunked. [#1577](https://github.com/bbartling/open-fdd/issues/1577)
- **Fault lanes:** hide empty leftovers from stale or excluded sensor results while keeping assessed-zero lanes visible.
  Existing NF points and history are not deleted. [#1578](https://github.com/bbartling/open-fdd/issues/1578)
- **Duration labels:** round displayed coverage and fault hours without changing stored values or comparisons.
  [#1579](https://github.com/bbartling/open-fdd/issues/1579)
- **Timescale preflight:** remote installer clients fail clearly when a loopback database address is unreachable and
  accept an explicit protected DSN override. [#1576](https://github.com/bbartling/open-fdd/issues/1576)
- **Documentation:** publish short SQL, pandas, API, and NF app guides; keep prompts and episode notes out of the
  Pages site. [#1580](https://github.com/bbartling/open-fdd/issues/1580)

See the full [CHANGELOG.md](https://github.com/bbartling/open-fdd/blob/master/CHANGELOG.md) and
[GitHub releases](https://github.com/bbartling/open-fdd/releases).
