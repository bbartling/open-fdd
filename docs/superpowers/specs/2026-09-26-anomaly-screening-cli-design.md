# Anomaly screening CLI (history_wide) — design

**Date:** 2026-09-26  
**Status:** Draft for review (design approved in chat; awaiting spec sign-off)  
**Package:** PyPI `open-fdd` (`open_fdd.analytics.anomaly`)  
**Practice data:** `/home/ben/Downloads/BUILDING_100/AHU_1` (`history_wide.csv` + `column_map.json`)  
**Related reading:** [Tiger Data — time series anomaly detection (SQL + Python)](https://www.tigerdata.com/learn/time-series-anomaly-detection-methods-sql-real-time-implementation)

## Goal

Ship a **PR-ready** offline screening tool in the Open-FDD Python package that:

1. Reads a device folder with wide historian CSV + column map.
2. Runs per-point anomaly detectors inspired by the Tiger Data guide (Z-score, MAD, STL residual, Isolation Forest) with alert deduplication.
3. Writes a scoreboard, a stacked bar chart of accumulated anomaly minutes, and up to **10 full-day zoom PNGs** for each of the **top-N** noisiest points (Open-FDD fault-strip plot style).
4. Keeps **SQL-portable** detectors (especially MAD / later Z-score) separable so they can later be re-expressed in DataFusion SQL; sklearn/STL remain Python-only.

## Non-goals (v1)

- Live Timescale / PostgreSQL connectors or continuous aggregates.
- Baking detectors into the DataFusion/Rust central stack in this PR (document portability only).
- Screening every zone space-temp column (v1 uses AHU IO from `column_map` only).
- Supervised / labeled training loops.

## Approach

**Offline screening CLI + library module (Approach A).**

Entry point: `open-fdd-anomaly`

```text
open-fdd-anomaly screen <folder> --out <outdir> [--top-n 5] [--max-days 10] [--methods zscore,mad,stl,iforest]
```

## Inputs

| Artifact | Role |
| --- | --- |
| `history_wide.csv` | Wide time series; time column `timestamp_utc` |
| `column_map.json` | AHU IO roles → column names (`points` / `column_roles`) |
| `columns.csv` | Optional metadata (unit / role); not required for v1 |

**Point set (v1):** only columns referenced by `column_map` AHU IO roles (e.g. DAT, MAT, RAT, OAT, duct static + SP, fans, valves, damper). Skip missing or non-numeric. Skip binary/status-like series (≤3 unique values) with a scoreboard `skipped_reason`.

## Detectors (per point, independent)

### Z-score (SQL-portable)

- Rolling mean + stddev over a window ≈ 1 day of samples (same window heuristic as MAD).
- Flag when `|x - mean| / stddev > threshold` (default ~3.0). Z-score is exactly “how many standard deviations from the mean.”
- Guard `stddev == 0`.
- Same SQL-portability rules as MAD (no sklearn/statsmodels imports).

### MAD (SQL-portable)

- Rolling median + MAD over a window ≈ 1 day of samples (window length from median sample interval).
- Flag when `|x - median| / MAD > threshold` (default ~3.5).
- Guard `MAD == 0`.
- Implementation should stay pandas/numpy so the logic maps cleanly to SQL window + percentile style later (Tiger Data MAD pattern).

### STL residual (Python-only)

- `statsmodels.tsa.seasonal.STL` with period ≈ 1 day (from median Δt).
- Flag residuals beyond a robust threshold (MAD of residual).
- Skip or degrade gracefully if series too short / constant for STL.

### Isolation Forest (Python-only)

- `sklearn.ensemble.IsolationForest` on simple features: value, short rolling mean/std, lag-1.
- Default `contamination≈0.01`; `is_anomaly` when predict == -1.
- Optional extras dependency (`open-fdd[anomaly]`).

### Dedupe (Tiger Data `LAG` pattern)

- Keep full boolean series for plots.
- **Events** = false→true transitions only.
- **Anomaly minutes** = flagged sample count × median Δt (minutes).

### Ranking

- Rank points by **total anomaly minutes** summed across selected methods (union for “how noisy”).
- Within a point, rank calendar days by anomaly minutes that day; emit ≤ `--max-days` (default 10).
- Top points: `--top-n` (default 5).

## Outputs

Under `--out`:

| Path | Content |
| --- | --- |
| `scoreboard.csv` | point, role, method, anomaly_minutes, event_count, skipped_reason |
| `scoreboard_bar.png` | Stacked bar: accumulated anomaly minutes per point × method |
| `days/<point>/<YYYY-MM-DD>.png` | Day zoom: value on top, anomaly bool strip(s) bottom (same layout spirit as `open_fdd.reporting.day_zoom` / online fault charts) |
| `dist/<point>_hist.png` | Distribution (histogram + optional KDE) of the point’s values; overlay or mark samples flagged by any selected method |
| `dist/<point>_box.png` | Box plot of the point’s value distribution (and optional by-day or by-anomaly vs normal split) |
| `overview/<point>_line.png` | Full-span line plot of the series with anomaly markers / shaded spans for flagged intervals |
| `README.md` | Methods, thresholds, versions, command that produced the run |

**Support plots (v1):** for every screened (non-skipped) point, emit the distribution + box + full-span line plots so Z-score / MAD findings are visually checkable against the raw distribution and time series. Day zooms remain limited to top-N × ≤10 worst days.

## Package layout

```text
open_fdd/analytics/anomaly/
  __init__.py
  screen.py       # orchestration: load → detect → rank → write
  detectors.py    # MAD (portable), STL, IsolationForest + dedupe helpers
  plots.py        # bar chart + day-zoom PNGs
  cli.py          # open-fdd-anomaly entry
```

- Register script in `pyproject.toml`: `open-fdd-anomaly = "open_fdd.analytics.anomaly.cli:main"`.
- Optional deps: `statsmodels`, `scikit-learn` under extras e.g. `anomaly` (and include in `dev`/`test` as appropriate).
- Tests: small synthetic series (injected spike / stuck / seasonal jump) asserting flags + scoreboard columns; plot smoke optional/light.

## SQL / DataFusion portability note

| Method | v1 home | Later port |
| --- | --- | --- |
| Z-score + MAD | Python, pure rolling stats | DataFusion SQL / continuous-aggregate style windows |
| STL | Python (`statsmodels`) | Stay Python or approximate with seasonal baselines in SQL later |
| Isolation Forest | Python (`sklearn`) | Stay Python batch / offline |

Detectors module should keep MAD (and any Z-score helper) free of sklearn/statsmodels imports so a future SQL rewrite can share thresholds and semantics.

## Practice validation

Before/with PR: editable install on OptiPlex, run against `BUILDING_100/AHU_1`, inspect bar + a handful of day zooms.

## Success criteria

- CLI runs on AHU_1 folder end-to-end without manual notebook steps.
- Scoreboard + bar chart exist; top-N points each have ≤10 day-zoom PNGs when enough anomalous days exist.
- Z-score and MAD paths have no hard dependency on sklearn/statsmodels.
- Support plots (hist, box, full-span line) exist for screened points; day zooms for top-N only.
- Design/docs state which methods are SQL-portable vs Python-only.
- PR targets default branch of `bbartling/open-fdd`.

## Open parameters (defaults OK for v1)

- `top-n=5`, `max-days=10`, Z-score threshold 3.0, MAD threshold 3.5, IF contamination 0.01, day boundary from timestamps (document UTC vs America/Chicago in README of each run).
