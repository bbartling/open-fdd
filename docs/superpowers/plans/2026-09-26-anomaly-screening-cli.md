# Anomaly Screening CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PR-ready `open-fdd-anomaly` CLI and `open_fdd.analytics.anomaly` module that screens AHU IO from a `history_wide` folder (Z-score, MAD, STL, Isolation Forest), writes scoreboard + support plots + top-N day zooms.

**Architecture:** Library module under `open_fdd/analytics/anomaly/` with SQL-portable pure-numpy/pandas detectors (Z-score, MAD) separated from Python-only STL/IF. CLI orchestrates load → detect → rank → plot. Plots mirror existing `day_zoom` fault-strip style.

**Tech Stack:** Python 3.10+, pandas/numpy (via existing oracle/reporting extras), matplotlib, statsmodels, scikit-learn; optional extras group `anomaly`.

**Spec:** `docs/superpowers/specs/2026-09-26-anomaly-screening-cli-design.md` (attach/uploads if present).

## Global Constraints

- Keep Z-score and MAD free of sklearn/statsmodels imports (DataFusion SQL portability later).
- v1 points = `column_map.json` AHU IO roles only (not all zone temps).
- Default CLI: `--top-n 5 --max-days 10 --methods zscore,mad,stl,iforest`.
- Support plots (line, hist, box) for every screened non-skipped point; day zooms only for top-N.
- Do not add Timescale/DB hooks in this PR.
- Follow existing package patterns (`pyproject.toml` scripts, `tests/analytics/`, matplotlib Agg).
- Open PR against default branch of `bbartling/open-fdd`.
- Do not commit secrets; do not require the user's Downloads path in CI (use synthetic fixtures).

---

### Task 1: Package scaffold + extras + CLI stub

**Files:**
- Create: `open_fdd/analytics/anomaly/__init__.py`
- Create: `open_fdd/analytics/anomaly/cli.py`
- Create: `open_fdd/analytics/anomaly/screen.py` (stub `screen_folder` raising NotImplemented or returning empty until later tasks)
- Modify: `pyproject.toml` (scripts + optional-dependencies `anomaly`)
- Test: `tests/analytics/anomaly/test_cli_help.py`

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int`; entry `open-fdd-anomaly`
- Produces: extras `anomaly = ["statsmodels>=...", "scikit-learn>=...", "matplotlib>=...", "pandas>=...", "numpy>=..."]` (align versions with existing `reporting`/`oracle` where possible)

- [ ] **Step 1:** Add failing test that imports `open_fdd.analytics.anomaly.cli` and runs `--help` / `screen --help` expecting exit 0 and usage text mentioning `screen`.
- [ ] **Step 2:** Implement stub package + argparse CLI (`screen` subcommand with `folder`, `--out`, `--top-n`, `--max-days`, `--methods`).
- [ ] **Step 3:** Wire `[project.scripts] open-fdd-anomaly = "open_fdd.analytics.anomaly.cli:main"` and extras group.
- [ ] **Step 4:** Run the new test; commit.

---

### Task 2: Load history_wide + column_map

**Files:**
- Create: `open_fdd/analytics/anomaly/io.py`
- Test: `tests/analytics/anomaly/test_io.py`
- Create fixture under `tests/analytics/anomaly/fixtures/mini_ahu/` (`history_wide.csv`, `column_map.json`)

**Interfaces:**
- Produces: `load_device_folder(path: Path) -> DeviceSeries` with timestamp index, point columns, role map
- Produces: `iter_ahu_io_points(column_map) -> list[tuple[role, column]]`

- [ ] **Step 1:** Write failing tests: loads mini fixture; resolves roles; skips missing columns.
- [ ] **Step 2:** Implement CSV/JSON load (`timestamp_utc` → DatetimeIndex tz-aware UTC).
- [ ] **Step 3:** Pass tests; commit.

---

### Task 3: Detectors — Z-score, MAD, dedupe (SQL-portable)

**Files:**
- Create: `open_fdd/analytics/anomaly/detectors.py`
- Test: `tests/analytics/anomaly/test_detectors_stats.py`

**Interfaces:**
- Produces: `rolling_zscore_flags(y, *, window, threshold=3.0) -> pd.Series[bool]`
- Produces: `rolling_mad_flags(y, *, window, threshold=3.5) -> pd.Series[bool]`
- Produces: `dedupe_events(flags: pd.Series) -> pd.Series[bool]` (True only on false→true)
- Produces: `anomaly_minutes(flags, median_dt) -> float`
- Produces: `is_binary_like(y, max_unique=3) -> bool`
- Constraint: no sklearn/statsmodels imports in this module section / prefer whole file free of those imports for portable funcs (split file if needed: `detectors_stats.py` vs `detectors_ml.py`)

- [ ] **Step 1:** Failing tests with synthetic spike / stuck / constant series.
- [ ] **Step 2:** Implement rolling Z-score + MAD + helpers; auto window from median Δt ≈ 1 day of samples.
- [ ] **Step 3:** Pass tests; commit.

---

### Task 4: Detectors — STL + Isolation Forest (Python-only)

**Files:**
- Create: `open_fdd/analytics/anomaly/detectors_ml.py` (or clearly gated section)
- Test: `tests/analytics/anomaly/test_detectors_ml.py`

**Interfaces:**
- Produces: `stl_residual_flags(y, *, period, threshold=...) -> pd.Series[bool]`
- Produces: `isolation_forest_flags(y, *, contamination=0.01, random_state=42) -> pd.Series[bool]`
- Lazy-import statsmodels/sklearn; clear error if extras missing.

- [ ] **Step 1:** Failing tests with seasonal + point anomaly synthetic data (skip if deps missing via pytest.importorskip).
- [ ] **Step 2:** Implement STL + IF with simple features (value, rolling mean/std, lag-1).
- [ ] **Step 3:** Pass tests; commit.

---

### Task 5: Screen orchestration + scoreboard

**Files:**
- Modify: `open_fdd/analytics/anomaly/screen.py`
- Test: `tests/analytics/anomaly/test_screen.py`

**Interfaces:**
- Produces: `screen_folder(folder, out_dir, *, top_n=5, max_days=10, methods=...) -> ScreenResult`
- Scoreboard columns: point, role, method, anomaly_minutes, event_count, skipped_reason
- Ranking: sum anomaly_minutes across methods; pick top_n; per point pick ≤ max_days by daily minutes

- [ ] **Step 1:** Failing test on mini fixture asserting scoreboard.csv schema and ranking.
- [ ] **Step 2:** Implement orchestration writing `scoreboard.csv` + run README.md.
- [ ] **Step 3:** Pass tests; commit.

---

### Task 6: Plots — bar, support (line/hist/box), day zooms

**Files:**
- Create: `open_fdd/analytics/anomaly/plots.py`
- Test: `tests/analytics/anomaly/test_plots.py` (smoke: files exist, non-empty)

**Interfaces:**
- Produces: `write_scoreboard_bar(scoreboard_df, path)`
- Produces: `write_support_plots(point, series, flags_by_method, out_dir)` → `overview/<point>_line.png`, `dist/<point>_hist.png`, `dist/<point>_box.png`
- Produces: `write_day_zoom(point, series, flags, day, path)` — value top, bool strip bottom (mirror `reporting/day_zoom.py` layout)

- [ ] **Step 1:** Failing smoke tests with tiny series.
- [ ] **Step 2:** Implement matplotlib Agg plots; wire from `screen_folder` for all screened points (support) + top-N days.
- [ ] **Step 3:** Pass tests; commit.

---

### Task 7: Docs + PR polish

**Files:**
- Ensure design/plan under `docs/superpowers/specs/` and `docs/superpowers/plans/` are in the PR
- Short usage blurb in package README or `docs/` if that is the local convention (check existing analytics docs; keep minimal)
- Modify: `pyproject.toml` version only if repo convention bumps on feature (prefer leave version to maintainer unless required)

- [ ] **Step 1:** Add brief usage example to nearest docs home (or anomaly module docstring / run README template).
- [ ] **Step 2:** Run focused pytest `tests/analytics/anomaly`.
- [ ] **Step 3:** Open PR to default branch with summary matching the design (SQL-portable vs Python-only called out).

## Done when

- `open-fdd-anomaly screen <folder> --out <outdir>` works conceptually on AHU_1-shaped folders (CI proves via mini fixture).
- PR open with tests green for the new suite.
- Z-score/MAD have no sklearn/statsmodels hard deps.
