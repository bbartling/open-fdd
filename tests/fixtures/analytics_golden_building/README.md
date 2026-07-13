# Analytics golden building fixture

Deterministic Vibe19 `ANALYTICS_GOLDEN_B1` package (data only) used to golden-test
Open-FDD Rust analytics rollups against `tests/fixtures/vibe19_analytics_golden/`.

- Source: Vibe19 `tests/fixtures/analytics_pkg` (not vendored Python)
- Open-FDD adds per-equipment `columns.csv` derived from `column_map.json`
- Layout: `ANALYTICS_GOLDEN_B1/{equipment}/history_wide.csv` + `columns.csv`

Do not commit private Building 100 data here.
