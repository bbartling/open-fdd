"""SQL per-point statistics (#1757): sensor_stats / diurnal_hourly / setpoints_latest SQL == the pandas twins in
open_fdd.analytics.point_stats.

SQLite and DuckDB run in-process. PostgreSQL runs only when POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1 are
set (the parity workflow's postgres job); each run uses its own throwaway database.
"""

from __future__ import annotations

import math
import os
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from open_fdd.analytics import point_stats as ps  # noqa: E402
from open_fdd.analytics import sql_point_stats as sps  # noqa: E402
from open_fdd.analytics.sql_anomaly import create_core, load_core  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
T0 = 1_772_409_600_000          # 2026-03-02 00:00 UTC
H = 3_600_000


def _long():
    """Two days on a jittered 5-minute grid: two OAT points (one role), SAT, a fan command, two setpoints, a point with
    one sample, NULLs, and a duplicate timestamp on a setpoint (ties keep the larger value)."""
    rng = np.random.default_rng(1757)
    rows = []
    for i in range(2 * 288):
        t = T0 + i * 300_000 + int(rng.integers(-40_000, 40_000))
        hour = ((t - T0) % (24 * H)) / H
        oat = 10 + 8 * math.sin((hour - 9) / 24 * 2 * math.pi) + float(rng.normal(0, 0.4))
        rows += [("ahu1/oat", "AHU-1", "oa_t", t, oat),
                 ("ahu2/oat", "AHU-2", "oa_t", t + 7_000, oat + 0.6),
                 ("ahu1/sat", "AHU-1", "sat", t, None if i % 37 == 0 else 13 + float(rng.normal(0, 0.3))),
                 ("ahu1/fan", "AHU-1", "fan_cmd", t, 1.0 if 6 <= hour < 18 else 0.0)]
        if i % 12 == 0:
            rows += [("ahu1/satsp", "AHU-1", "sat_sp", t, 12.8 + (i % 48) / 48),
                     ("vav1/zsp", "VAV-1", "zone_air_temp_sp", t, 22.0 if 6 <= hour < 18 else 18.0)]
    last = rows[-1][3]
    rows += [("ahu1/satsp", "AHU-1", "sat_sp", last + 60_000, 13.1), ("ahu1/satsp", "AHU-1", "sat_sp", last + 60_000, 13.4),
             ("one/x", "AHU-1", "duct_static", T0 + 5 * H, 250.0)]
    return pd.DataFrame(rows, columns=list(ps.LONG_COLUMNS))


def _connect(engine):
    if engine == "duckdb":
        return pytest.importorskip("duckdb").connect(":memory:")
    return sqlite3.connect(":memory:")


def _load(conn, engine, long):
    pts = long.drop_duplicates("point_key")
    points = [{"site_id": "local", "point_key": r.point_key, "equipment_id": r.equipment_id, "role": r.role}
              for r in pts.itertuples()]
    samples = [("local", r.point_key, int(r.ts_ms), None if pd.isna(r.value) else float(r.value))
               for r in long.itertuples()]
    create_core(conn, engine)
    load_core(conn, engine, points, samples)


def _same(got: list[dict], want, keys, label):
    want = want.to_dict("records")
    assert len(got) == len(want), f"{label}: {len(got)} rows vs {len(want)}"
    for g, w in zip(got, want):
        for k in keys:
            a, b = g[k], w[k]
            if isinstance(b, float) and (math.isnan(b)):
                assert a is None, (label, k, g)
            elif isinstance(b, (float, np.floating)):
                assert a == pytest.approx(float(b), rel=1e-12, abs=1e-9), (label, k, g, w)
            else:
                assert a == (int(b) if isinstance(b, (np.integer,)) else b), (label, k, g, w)


def _check_all(conn, engine, long, window=None):
    kw = dict(start_ms=window[0], end_ms=window[1]) if window else {}
    _same(sps.run_sensor_stats_sql(conn, engine, **kw), ps.sensor_stats(long, **kw),
          ["point_key", "equipment_id", "role", "n", "min_val", "max_val", "avg_val", "stddev_val", "first_ms",
           "last_ms"], f"{engine} stats")
    _same(sps.run_diurnal_sql(conn, engine, **kw), ps.diurnal_hourly(long, **kw),
          ["point_key", "role", "hour_utc", "avg_val", "n"], f"{engine} diurnal")
    roles = sps.default_setpoint_roles()
    _same(sps.run_setpoints_sql(conn, engine, **kw), ps.latest_setpoints(long, roles, **kw),
          ["point_key", "role", "t", "value"], f"{engine} setpoints")


def test_packaged_sql_is_the_repo_file():
    for name in ("sensor_stats", "diurnal_hourly", "setpoints_latest"):
        repo = (ROOT / "sql" / "analytics" / f"{name}.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
        assert sps.template(name).replace("\r\n", "\n") == repo, name


@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_matches_pandas(engine):
    long = _long()
    conn = _connect(engine)
    try:
        _load(conn, engine, long)
        _check_all(conn, engine, long)
        _check_all(conn, engine, long, window=(T0 + 6 * H, T0 + 30 * H))
    finally:
        conn.close()


def test_semantics_pinned():
    long = _long()
    conn = sqlite3.connect(":memory:")
    try:
        _load(conn, "sqlite", long)
        stats = {r["point_key"]: r for r in sps.run_sensor_stats_sql(conn, "sqlite")}
        assert stats["one/x"]["n"] == 1 and stats["one/x"]["stddev_val"] is None      # one sample: no spread
        assert stats["ahu1/sat"]["n"] == 576 - len(range(0, 576, 37))                  # NULLs are not samples
        assert {"ahu1/oat", "ahu2/oat"} <= set(stats)                                   # one role, two rows
        hours = {r["hour_utc"] for r in sps.run_diurnal_sql(conn, "sqlite") if r["point_key"] == "ahu1/fan"}
        assert hours == set(range(24))
        assert not any(r["role"] == "duct_static" for r in sps.run_diurnal_sql(conn, "sqlite"))  # not a diurnal role
        sp = {r["point_key"]: r for r in sps.run_setpoints_sql(conn, "sqlite")}
        assert set(sp) == {"ahu1/satsp", "vav1/zsp"}                                    # setpoint roles only
        assert sp["ahu1/satsp"]["value"] == 13.4                                         # tie: the larger value
    finally:
        conn.close()


def test_render_quotes_and_checks():
    sql = sps.render_setpoints_sql("sqlite", site_id="s'1", point_keys=["a'b"], roles=["x'y"], start_ms=1, end_ms=2)
    assert "'s''1'" in sql and "'a''b'" in sql and "'x''y'" in sql and "t >= 1" in sql and "{" not in sql
    assert "1 = 0" in sps.render_diurnal_sql("sqlite", roles=[])
    with pytest.raises(ValueError):
        sps.render_sensor_stats_sql("sqlite", start_ms=5, end_ms=5)
    with pytest.raises(ValueError):
        sps.render_sensor_stats_sql("oracle")


@pytest.mark.skipif(not (os.environ.get("POSTGRES_TEST_URL") and os.environ.get("OPENFDD_PG_TEST_DISPOSABLE") == "1"),
                    reason="needs POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1")
def test_postgres_matches_pandas():
    psycopg = pytest.importorskip("psycopg")
    long = _long()
    base = os.environ["POSTGRES_TEST_URL"]
    dbname = f"openfdd_pstats_{secrets.token_hex(6)}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{dbname}"')
    try:
        url = urlunparse(urlparse(base)._replace(path=f"/{dbname}"))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            _load(conn, "postgres", long)
            _check_all(conn, "postgres", long)
            _check_all(conn, "postgres", long, window=(T0 + 6 * H, T0 + 30 * H))
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')


# ---- slice 2: role timeseries, anomaly coverage, PID hunting proxy ------------------------------------------------
def _long2():
    """PID / anomaly cases: a hunting zone temp, a calm SAT, valve commands in percent and in 0-1, a hunting damper,
    duct static, a constant MAT, a short RAT, and a bound OAT point with no samples at all."""
    rng = np.random.default_rng(17572)
    rows = []
    for i in range(96):
        t = T0 + i * 300_000 + int(rng.integers(-30_000, 30_000))
        rows += [("z/zt", "VAV-1", "zone_t", t, 22 + (6 if i % 2 else -6) + float(rng.normal(0, 0.2))),
                 ("a/sat", "AHU-1", "sat", t, 13 + float(rng.normal(0, 0.3))),
                 ("a/clg", "AHU-1", "clg_valve_pct", t, 40 + float(rng.normal(0, 2))),          # percent, calm
                 ("a/dmp", "AHU-1", "oa_damper_pct", t, 0.2 if i % 2 else 0.6),                # 0-1, hunting
                 ("a/dsp", "AHU-1", "duct_static", t, 250 + float(rng.normal(0, 15))),
                 ("a/mat", "AHU-1", "mat", t, 18.0)]                                          # constant
        if i < 10:
            rows.append(("a/rat", "AHU-1", "rat", t, 21 + i * 0.1))                           # short
    return pd.DataFrame(rows, columns=list(ps.LONG_COLUMNS))


def _load2(conn, engine, long):
    _load(conn, engine, long)
    rows = [("local", "a/oat", "AHU-1", "oa_t")]                                               # bound, no samples
    if engine == "postgres":
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO fdd.point VALUES (%s, %s, %s, %s)", rows)
    else:
        conn.executemany("INSERT INTO fdd.point VALUES (?, ?, ?, ?)", rows)


def _points2(long):
    pts = long.drop_duplicates("point_key").loc[:, ["point_key", "equipment_id", "role"]]
    return pd.concat([pts, pd.DataFrame([("a/oat", "AHU-1", "oa_t")], columns=pts.columns)], ignore_index=True)


def _check_slice2(conn, engine, long, window=None):
    kw = dict(start_ms=window[0], end_ms=window[1]) if window else {}
    roles = ["zone_t", "sat", "duct_static"]
    _same(sps.run_role_timeseries_sql(conn, engine, roles, limit=77, **kw),
          ps.role_timeseries(long, roles, limit=77, **kw), ["point_key", "role", "t", "value"], f"{engine} timeseries")
    _same(sps.run_anomaly_coverage_sql(conn, engine, **kw), ps.anomaly_coverage(_points2(long), long, **kw),
          ["point_key", "role", "n", "var_val", "is_short", "is_constant"], f"{engine} coverage")
    _same(sps.run_pid_hunting_sql(conn, engine, **kw), ps.pid_hunting_proxy(long, **kw),
          ["point_key", "role", "n", "avg_val", "var_val", "is_hunting"], f"{engine} pid")


@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_slice2_matches_pandas(engine):
    long = _long2()
    conn = _connect(engine)
    try:
        _load2(conn, engine, long)
        _check_slice2(conn, engine, long)
        _check_slice2(conn, engine, long, window=(T0 + 2 * H, T0 + 6 * H))
    finally:
        conn.close()


def test_slice2_semantics_pinned():
    long = _long2()
    conn = sqlite3.connect(":memory:")
    try:
        _load2(conn, "sqlite", long)
        cov = {r["point_key"]: r for r in sps.run_anomaly_coverage_sql(conn, "sqlite")}
        assert cov["a/oat"]["n"] == 0 and cov["a/oat"]["is_short"] == 1 and cov["a/oat"]["var_val"] is None
        assert cov["a/mat"]["is_constant"] == 1 and cov["a/rat"]["is_short"] == 1 and cov["a/sat"]["is_short"] == 0
        assert "a/clg" not in cov                                                     # not an anomaly role
        pid = {r["point_key"]: r for r in sps.run_pid_hunting_sql(conn, "sqlite")}
        assert pid["z/zt"]["is_hunting"] == 1 and pid["a/sat"]["is_hunting"] == 0
        assert pid["a/dmp"]["is_hunting"] == 1                                        # 0-1 command: 0.2 / 0.6 swing
        assert pid["a/clg"]["is_hunting"] == 0 and abs(pid["a/clg"]["avg_val"] - 0.40) < 0.01   # percent scaled to 0-1
        assert pid["a/dsp"]["is_hunting"] == 0 and "a/rat" not in pid                 # rat is not a PID role
        assert list(pid)[0] == "a/dsp"                                                # largest spread first
        ts = sps.run_role_timeseries_sql(conn, "sqlite", ["zone_t"], limit=5)
        assert len(ts) == 5 and ts[0]["t"] >= ts[-1]["t"]                             # newest first, capped
    finally:
        conn.close()
    with pytest.raises(ValueError):
        sps.render_role_timeseries_sql("sqlite", ["sat"], limit=0)
    with pytest.raises(ValueError):
        sps.render_anomaly_coverage_sql("sqlite", window=1)


@pytest.mark.skipif(not (os.environ.get("POSTGRES_TEST_URL") and os.environ.get("OPENFDD_PG_TEST_DISPOSABLE") == "1"),
                    reason="needs POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1")
def test_postgres_slice2_matches_pandas():
    psycopg = pytest.importorskip("psycopg")
    long = _long2()
    base = os.environ["POSTGRES_TEST_URL"]
    dbname = f"openfdd_pstats2_{secrets.token_hex(6)}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{dbname}"')
    try:
        url = urlunparse(urlparse(base)._replace(path=f"/{dbname}"))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            _load2(conn, "postgres", long)
            _check_slice2(conn, "postgres", long)
            _check_slice2(conn, "postgres", long, window=(T0 + 2 * H, T0 + 6 * H))
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
