"""SQL BAS vs web OAT (#1649): sql/analytics/bas_vs_web_oat.sql == weather_resolver.bas_vs_web_oat_stats.

SQLite and DuckDB run in-process. PostgreSQL runs only when POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1 are
set (the parity workflow's postgres job, which fails on a skip); each run uses its own throwaway database.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from open_fdd.analytics.sql_anomaly import create_core, load_core  # noqa: E402
from open_fdd.analytics.sql_bas_web import bas_web_sql_template, render_bas_web_sql, run_bas_web_sql  # noqa: E402
from open_fdd.analytics.weather_resolver import bas_vs_web_oat_stats, default_web_max_age_seconds  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
H = 3_600_000
T0 = pd.Timestamp("2026-05-04", tz="UTC")


def _postgres_configured() -> bool:
    return bool(os.environ.get("POSTGRES_TEST_URL")) and os.environ.get("OPENFDD_PG_TEST_DISPOSABLE") == "1"


def _ms(index) -> np.ndarray:
    return (pd.DatetimeIndex(index).tz_convert("UTC").as_unit("ns").asi8 // 1_000_000).astype("int64")


def _series():
    """Hourly web OAT (with a 5 h outage) and two BAS sensors every 5 min: one 1.2 C warm, one 3 C warm at noon."""
    rng = np.random.default_rng(1649)
    web_idx = pd.date_range(T0, periods=24 * 5, freq="h")
    web_idx = web_idx[(web_idx < T0 + pd.Timedelta(hours=50)) | (web_idx >= T0 + pd.Timedelta(hours=55))]
    curve = lambda idx: 15 + 8 * np.sin((np.asarray(idx.hour, dtype=float) - 9) / 24 * 2 * np.pi)  # noqa: E731
    web = pd.Series(curve(web_idx), index=web_idx)
    bas_idx = pd.date_range(T0 + pd.Timedelta(minutes=2), periods=12 * 24 * 5, freq="5min")
    bas1 = pd.Series(curve(bas_idx) + 1.2 + rng.normal(0, 0.3, len(bas_idx)), index=bas_idx)
    noon = (np.asarray(bas_idx.hour) >= 11) & (np.asarray(bas_idx.hour) < 14)
    bas2 = pd.Series(curve(bas_idx) + np.where(noon, 3.0, 0.5), index=bas_idx)
    return web, {"AHU-1": bas1, "AHU-2": bas2}


def _core(web, bas_by_eq):
    points = [{"site_id": "local", "point_key": "web", "equipment_id": None, "role": "web_oa_t"}]
    samples = [("local", "web", int(t), float(v)) for t, v in zip(_ms(web.index), web.to_numpy())]
    for eq, s in bas_by_eq.items():
        points.append({"site_id": "local", "point_key": f"{eq}/oat", "equipment_id": eq, "role": "oa_t"})
        samples += [("local", f"{eq}/oat", int(t), float(v)) for t, v in zip(_ms(s.index), s.to_numpy())]
    return points, samples


def _run(engine, points, samples, pairs, **kw):
    if engine == "duckdb":
        duckdb = pytest.importorskip("duckdb")
        conn = duckdb.connect(":memory:")
    else:
        conn = sqlite3.connect(":memory:")
    try:
        create_core(conn, engine)
        load_core(conn, engine, points, samples)
        return {r["equipment_id"]: r for r in run_bas_web_sql(conn, engine, pairs, **kw)}
    finally:
        conn.close()


def test_packaged_sql_is_the_repo_file():
    repo = (ROOT / "sql" / "analytics" / "bas_vs_web_oat.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert bas_web_sql_template().replace("\r\n", "\n") == repo


def test_render_quotes_and_checks():
    sql = render_bas_web_sql("sqlite", [("o'ahu", "b'1", "w", 10)], site_id="s'1", start_ms=1, end_ms=2)
    assert "'o''ahu'" in sql and "'b''1'" in sql and "'s''1'" in sql and "w.t >= 1 - w.max_age_ms" in sql
    assert "{" not in sql
    for kw in ({"band_c": -1}, {"start_ms": 5, "end_ms": 5}):
        with pytest.raises(ValueError):
            render_bas_web_sql("sqlite", [("A", "b", "w", 10)], **kw)
    with pytest.raises(ValueError):
        render_bas_web_sql("sqlite", [("A", "b", "w", -1)])
    with pytest.raises(ValueError):
        render_bas_web_sql("oracle", [("A", "b", "w", 10)])


@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_matches_pandas(engine):
    web, bas_by_eq = _series()
    points, samples = _core(web, bas_by_eq)
    ages = {eq: default_web_max_age_seconds(s, web) for eq, s in bas_by_eq.items()}
    assert ages["AHU-1"] == pytest.approx(5400.0)  # 1.5 x the hourly web cadence
    got = _run(engine, points, samples, [(eq, f"{eq}/oat", "web", int(ages[eq] * 1000)) for eq in bas_by_eq])
    for eq, bas in bas_by_eq.items():
        want = bas_vs_web_oat_stats(bas, web)
        assert 0 < want["n"] < len(bas)  # the web outage leaves BAS samples unpaired
        assert got[eq]["n"] == want["n"]
        for k in ("bias", "mae", "max_abs", "within_band"):
            assert got[eq][k] == pytest.approx(want[k], abs=1e-9), (eq, k)
    assert got["AHU-1"]["within_band"] > got["AHU-2"]["within_band"]


def test_window_bounds_bas_but_web_may_precede_it():
    web = pd.Series([10.0, 20.0], index=[T0, T0 + pd.Timedelta(hours=1)])
    bas = pd.Series([11.0, 21.0, 22.0], index=[T0 + pd.Timedelta(minutes=50), T0 + pd.Timedelta(minutes=70),
                                               T0 + pd.Timedelta(minutes=80)])
    points, samples = _core(web, {"A": bas})
    start = int(_ms([T0 + pd.Timedelta(minutes=45)])[0])
    rows = _run("sqlite", points, samples, [("A", "A/oat", "web", H)], start_ms=start)
    # the 10.0 reading at T0 is before the window but within the age limit, so the 50-minute sample pairs with it
    assert rows["A"]["n"] == 3 and rows["A"]["bias"] == pytest.approx((1.0 + 1.0 + 2.0) / 3)
    short = _run("sqlite", points, samples, [("A", "A/oat", "web", 30 * 60 * 1000)])
    assert short["A"]["n"] == 2  # with a 30 min limit the 50-minute sample is unpaired


@pytest.mark.skipif(not _postgres_configured(), reason="needs POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1")
def test_postgres_bas_web_matches_pandas():
    psycopg = pytest.importorskip("psycopg")
    web, bas_by_eq = _series()
    points, samples = _core(web, bas_by_eq)
    pairs = [(eq, f"{eq}/oat", "web", int(default_web_max_age_seconds(s, web) * 1000)) for eq, s in bas_by_eq.items()]
    base = os.environ["POSTGRES_TEST_URL"]
    dbname = f"openfdd_basweb_{secrets.token_hex(6)}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{dbname}"')
    try:
        url = urlunparse(urlparse(base)._replace(path=f"/{dbname}"))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            create_core(conn, "postgres")
            load_core(conn, "postgres", points, samples)
            got = {r["equipment_id"]: r for r in run_bas_web_sql(conn, "postgres", pairs)}
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
    for eq, bas in bas_by_eq.items():
        want = bas_vs_web_oat_stats(bas, web)
        assert got[eq]["n"] == want["n"]
        for k in ("bias", "mae", "max_abs", "within_band"):
            assert got[eq][k] == pytest.approx(want[k], abs=1e-9)


# ---- per-sample pairs (#1649: the NF chart points) ---------------------------------------------------------------
@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_points_match_the_pandas_pairs(engine):
    from open_fdd.analytics.sql_bas_web import bas_web_points_sql_template, run_bas_web_points_sql
    from open_fdd.analytics.weather_resolver import bas_vs_web_pairs

    repo = (ROOT / "sql" / "analytics" / "bas_vs_web_points.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert bas_web_points_sql_template().replace("\r\n", "\n") == repo
    web, bas_by_eq = _series()
    points, samples = _core(web, bas_by_eq)
    pairs = [(eq, f"{eq}/oat", "web", int(default_web_max_age_seconds(s, web) * 1000)) for eq, s in bas_by_eq.items()]
    if engine == "duckdb":
        conn = pytest.importorskip("duckdb").connect(":memory:")
    else:
        conn = sqlite3.connect(":memory:")
    try:
        create_core(conn, engine)
        load_core(conn, engine, points, samples)
        got = run_bas_web_points_sql(conn, engine, pairs)
        stats = {r["equipment_id"]: r for r in run_bas_web_sql(conn, engine, pairs)}
    finally:
        conn.close()
    for eq, bas in bas_by_eq.items():
        want = bas_vs_web_pairs(bas, web)
        mine = [r for r in got if r["equipment_id"] == eq]
        assert len(mine) == len(want) == stats[eq]["n"]
        assert [r["t"] for r in mine] == list(_ms(want["t"]))
        for k in ("bas", "web", "d"):
            assert [r[k] for r in mine] == pytest.approx(list(want[k]), abs=1e-9), (eq, k)
        assert sum(r["d"] for r in mine) / len(mine) == pytest.approx(stats[eq]["bias"], abs=1e-9)
