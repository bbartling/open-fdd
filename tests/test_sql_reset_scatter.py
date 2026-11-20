"""SQL reset scatters (#1757): sql/analytics/reset_scatter.sql == open_fdd.analytics.sql_reset_scatter.reset_scatter_pairs
(the pandas as-of pairing of weather_resolver.bas_vs_web_pairs). SQLite and DuckDB in-process; PostgreSQL only with
POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1 (the parity workflow's postgres job), on a throwaway database."""

from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from open_fdd.analytics import sql_reset_scatter as rs  # noqa: E402
from open_fdd.analytics.sql_anomaly import create_core, load_core  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
T0 = pd.Timestamp("2026-01-05", tz="UTC")


def _ms(index):
    return (pd.DatetimeIndex(index).tz_convert("UTC").as_unit("ns").asi8 // 1_000_000).astype("int64")


def _series():
    """Hourly web OAT with a 4 h outage; a SAT that resets with OAT and an HW supply on one AHU, every 5 min."""
    rng = np.random.default_rng(17575)
    web_idx = pd.date_range(T0, periods=72, freq="h")
    web_idx = web_idx[(web_idx < T0 + pd.Timedelta(hours=30)) | (web_idx >= T0 + pd.Timedelta(hours=34))]
    curve = lambda idx: -5 + 10 * np.sin((np.asarray(idx.hour, dtype=float) - 9) / 24 * 2 * np.pi)  # noqa: E731
    web = pd.Series(curve(web_idx), index=web_idx)
    idx = pd.date_range(T0 + pd.Timedelta(minutes=3), periods=12 * 72, freq="5min")
    oat = curve(idx)
    sat = pd.Series(np.clip(18 - 0.3 * oat, 12, 18) + rng.normal(0, 0.1, len(idx)), index=idx)
    hws = pd.Series(np.clip(70 - 1.5 * oat, 50, 80) + rng.normal(0, 0.5, len(idx)), index=idx)
    return web, {"sat": sat, "hws": hws}


def _core(web, ys):
    points = [{"site_id": "local", "point_key": "web", "equipment_id": None, "role": "web_oa_t"},
              {"site_id": "local", "point_key": "ahu/sat", "equipment_id": "AHU-1", "role": "sat"},
              {"site_id": "local", "point_key": "blr/hws", "equipment_id": "BLR-1", "role": "hw_supply_t"}]
    keys = {"sat": "ahu/sat", "hws": "blr/hws"}
    samples = [("local", "web", int(t), float(v)) for t, v in zip(_ms(web.index), web.to_numpy())]
    for name, s in ys.items():
        samples += [("local", keys[name], int(t), float(v)) for t, v in zip(_ms(s.index), s.to_numpy())]
    return points, samples


PAIRS = [("ahu-sat", "AHU-1", "ahu/sat", "web", 5_400_000), ("blr-hws", "BLR-1", "blr/hws", "web", 5_400_000)]


def _check(got, web, ys, window=None):
    by = {}
    for r in got:
        by.setdefault(r["scatter_id"], []).append(r)
    for sid, name in (("ahu-sat", "sat"), ("blr-hws", "hws")):
        y = ys[name]
        if window:
            y = y[(_ms(y.index) >= window[0]) & (_ms(y.index) < window[1])]
        want = rs.reset_scatter_pairs(y, web, max_age_seconds=5400)
        mine = by.get(sid, [])
        assert len(mine) == len(want), (sid, len(mine), len(want))
        assert [r["t"] for r in mine] == list(_ms(want["t"]))
        assert [r["x"] for r in mine] == pytest.approx(list(want["x"]), abs=1e-9)
        assert [r["y"] for r in mine] == pytest.approx(list(want["y"]), abs=1e-9)


def _run(engine, points, samples, **kw):
    conn = pytest.importorskip("duckdb").connect(":memory:") if engine == "duckdb" else sqlite3.connect(":memory:")
    try:
        create_core(conn, engine)
        load_core(conn, engine, points, samples)
        return rs.run_reset_scatter_sql(conn, engine, PAIRS, **kw)
    finally:
        conn.close()


def test_packaged_sql_is_the_repo_file():
    repo = (ROOT / "sql" / "analytics" / "reset_scatter.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert rs.reset_scatter_sql_template().replace("\r\n", "\n") == repo


@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_matches_pandas(engine):
    web, ys = _series()
    points, samples = _core(web, ys)
    got = _run(engine, points, samples)
    _check(got, web, ys)
    assert {r["equipment_id"] for r in got} == {"AHU-1", "BLR-1"}
    # the outage leaves y samples unpaired (more than 90 min after the last web reading)
    assert len([r for r in got if r["scatter_id"] == "ahu-sat"]) < len(ys["sat"])
    win = (int(_ms([T0 + pd.Timedelta(hours=12)])[0]), int(_ms([T0 + pd.Timedelta(hours=40)])[0]))
    _check(_run(engine, points, samples, start_ms=win[0], end_ms=win[1]), web, ys, window=win)


def test_render_checks():
    sql = rs.render_reset_scatter_sql("sqlite", [("s'1", "e'1", "y'k", "x", 10)], site_id="z'z", start_ms=1, end_ms=2)
    assert "'s''1'" in sql and "'y''k'" in sql and "'z''z'" in sql and "w.t >= 1 - w.max_age_ms" in sql and "{" not in sql
    for bad in ([("a", "e", "y", "x", -1)], [("a", "e", "y", "x", 1), ("a", "e", "y2", "x", 1)]):
        with pytest.raises(ValueError):
            rs.render_reset_scatter_sql("sqlite", bad)
    with pytest.raises(ValueError):
        rs.render_reset_scatter_sql("oracle", [("a", "e", "y", "x", 1)])
    assert rs.run_reset_scatter_sql(None, "sqlite", []) == []


@pytest.mark.skipif(not (os.environ.get("POSTGRES_TEST_URL") and os.environ.get("OPENFDD_PG_TEST_DISPOSABLE") == "1"),
                    reason="needs POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1")
def test_postgres_matches_pandas():
    psycopg = pytest.importorskip("psycopg")
    web, ys = _series()
    points, samples = _core(web, ys)
    base = os.environ["POSTGRES_TEST_URL"]
    dbname = f"openfdd_reset_{secrets.token_hex(6)}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{dbname}"')
    try:
        url = urlunparse(urlparse(base)._replace(path=f"/{dbname}"))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            create_core(conn, "postgres")
            load_core(conn, "postgres", points, samples)
            got = rs.run_reset_scatter_sql(conn, "postgres", PAIRS)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
    _check(got, web, ys)
