"""SQL rolling z-score (#1649): sql/analytics/anomaly_zscore.sql == rolling_zscore_flags on the seeded parity dataset.

SQLite always runs (standard library); DuckDB when installed; standalone PostgreSQL when POSTGRES_TEST_URL and
OPENFDD_PG_TEST_DISPOSABLE=1 are set (the parity workflow's postgres job, which fails on a skip).
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest

pd = pytest.importorskip("pandas")

from open_fdd.analytics.anomaly.detectors import dedupe_events, rolling_zscore_flags  # noqa: E402
from open_fdd.analytics.sql_anomaly import (  # noqa: E402
    create_core,
    load_core,
    render_zscore_sql,
    run_zscore_sql,
    zscore_flags_sql,
    zscore_sql_template,
)
from open_fdd.parity import generate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES = [(12, 3.0), (12, 2.0), (48, 2.5)]


def _postgres_configured() -> bool:
    return bool(os.environ.get("POSTGRES_TEST_URL")) and os.environ.get("OPENFDD_PG_TEST_DISPOSABLE") == "1"


@pytest.fixture(scope="module", params=["basic", "edge"])
def core(request):
    ds = generate(0, 2, 3, request.param)
    points, samples = ds.to_core_rows()
    return [{**p, "site_id": "parity"} for p in points], samples


def _reference(samples, window, threshold):
    by_key: dict[str, list[tuple[int, float]]] = {}
    for _site, key, ts, value in samples:
        by_key.setdefault(key, []).append((ts, value))
    flags, events = set(), set()
    for key, rows in by_key.items():
        rows.sort()
        series = pd.Series([v for _, v in rows], index=[t for t, _ in rows], dtype=float)
        f = rolling_zscore_flags(series, window=window, threshold=threshold)
        e = dedupe_events(f)
        flags |= {(key, int(t)) for t in f.index[f.to_numpy()]}
        events |= {(key, int(t)) for t in e.index[e.to_numpy()]}
    return flags, events


def _ms(value) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return int(ts.value // 1_000_000)


def _check(rows, samples, window, threshold):
    got = {(r["point_key"], _ms(r["ts"])) for r in rows if r["is_anomaly"]}
    events = {(r["point_key"], _ms(r["ts"])) for r in rows if r["is_event"]}
    want, want_events = _reference(samples, window, threshold)
    assert len(rows) == len(samples)
    assert got == want
    assert events == want_events
    return len(want)


def test_packaged_sql_is_the_repo_file():
    repo = (ROOT / "sql" / "analytics" / "anomaly_zscore.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert zscore_sql_template().replace("\r\n", "\n") == repo


def test_render_checks_inputs():
    sql = render_zscore_sql(12, 3.0, site_id="o'brien", point_keys=["a'b"])
    assert "'o''brien'" in sql and "'a''b'" in sql and "11 PRECEDING" in sql and "{" not in sql
    for bad in ({"window": 1}, {"window": 12, "threshold": 0}, {"window": 12, "threshold": float("nan")}):
        with pytest.raises(ValueError):
            render_zscore_sql(**bad)


@pytest.mark.parametrize("window,threshold", CASES)
def test_sqlite_matches_pandas(core, window, threshold):
    points, samples = core
    conn = sqlite3.connect(":memory:")
    try:
        create_core(conn, "sqlite")
        load_core(conn, "sqlite", points, samples)
        rows = run_zscore_sql(conn, "sqlite", window=window, threshold=threshold, site_id="parity")
    finally:
        conn.close()
    n = _check(rows, samples, window, threshold)
    if threshold <= 2.5:
        assert n > 0  # the comparison is not vacuous


@pytest.mark.parametrize("window,threshold", CASES)
def test_duckdb_matches_pandas(core, window, threshold):
    duckdb = pytest.importorskip("duckdb")
    points, samples = core
    conn = duckdb.connect(":memory:")
    try:
        create_core(conn, "duckdb")
        load_core(conn, "duckdb", points, samples)
        rows = run_zscore_sql(conn, "duckdb", window=window, threshold=threshold, site_id="parity")
    finally:
        conn.close()
    _check(rows, samples, window, threshold)


@pytest.mark.skipif(not _postgres_configured(), reason="needs POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1")
def test_postgres_zscore_matches_pandas(core):
    psycopg = pytest.importorskip("psycopg")
    points, samples = core
    base = os.environ["POSTGRES_TEST_URL"]
    dbname = f"openfdd_zscore_{secrets.token_hex(6)}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{dbname}"')
    try:
        url = urlunparse(urlparse(base)._replace(path=f"/{dbname}"))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            create_core(conn, "postgres")
            load_core(conn, "postgres", points, samples)
            for window, threshold in CASES:
                rows = run_zscore_sql(conn, "postgres", window=window, threshold=threshold, site_id="parity")
                _check(rows, samples, window, threshold)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')


@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_wide_frame_helper_matches_pandas(engine):
    if engine == "duckdb":
        pytest.importorskip("duckdb")
    import numpy as np

    rng = np.random.default_rng(0)
    idx = pd.date_range("2026-01-05", periods=600, freq="5min", tz="UTC")
    frame = pd.DataFrame({"a": rng.normal(20, 1, 600), "b": np.sin(np.arange(600) / 20) + rng.normal(0, 0.05, 600)},
                         index=idx)
    frame.iloc[300, 0] += 8.0
    got = zscore_flags_sql(frame, window=24, threshold=2.5, engine=engine)
    for col in frame.columns:
        want = rolling_zscore_flags(frame[col], window=24, threshold=2.5)
        assert got[col].tolist() == want.tolist()
    assert bool(got.iloc[300, 0])


def test_screen_engine_sql_matches_pandas(tmp_path):
    pytest.importorskip("matplotlib")
    pytest.importorskip("sklearn")
    import numpy as np

    from open_fdd.analytics.anomaly.screen import screen_folder

    rng = np.random.default_rng(1)
    idx = pd.date_range("2026-01-05", periods=2 * 288, freq="5min", tz="UTC")
    folder = tmp_path / "AHU_1"
    folder.mkdir()
    hist = pd.DataFrame({"timestamp_utc": idx.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "SAT": 13 + rng.normal(0, 0.3, len(idx)), "MAT": 18 + rng.normal(0, 0.5, len(idx))})
    hist.loc[400, "SAT"] = 25.0
    hist.to_csv(folder / "history_wide.csv", index=False)
    (folder / "column_map.json").write_text(json.dumps({"equipType": "AHU", "points": {"sat": "SAT", "mat": "MAT"}}),
                                            encoding="utf-8")
    a = screen_folder(folder, tmp_path / "pandas", methods=["zscore"], top_n=0, max_days=0)
    b = screen_folder(folder, tmp_path / "sql", methods=["zscore"], top_n=0, max_days=0, engine="sql")
    pd.testing.assert_frame_equal(a.scoreboard, b.scoreboard)
    assert "Z-score engine: **sql**" in (tmp_path / "sql" / "README.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        screen_folder(folder, tmp_path / "x", methods=["zscore"], engine="spark")


def test_wide_frame_helper_keeps_row_identity_with_repeated_timestamps():
    t = pd.to_datetime(["2026-01-05 00:00", "2026-01-05 00:05", "2026-01-05 00:10", "2026-01-05 00:10"], utc=True)
    frame = pd.DataFrame({"a": [0.0, 0.0, 10.0, float("nan")]}, index=t)
    got = zscore_flags_sql(frame, window=3, threshold=1.0, engine="sqlite")
    assert got["a"].tolist() == [False, False, True, False]
    frame.iloc[3, 0] = 1.0
    with pytest.raises(ValueError, match="same millisecond"):
        zscore_flags_sql(frame, window=3, threshold=1.0, engine="sqlite")
