"""SQL economizer metrics (#1649): sql/analytics/economizer_metrics.sql == economizer_free_cooling_diagnostics metrics.

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

from open_fdd.analytics.core import economizer_free_cooling_diagnostics  # noqa: E402
from open_fdd.analytics.sql_anomaly import create_core, load_core  # noqa: E402
from open_fdd.analytics.sql_economizer import (  # noqa: E402
    economizer_metrics_sql,
    economizer_sql_template,
    plan_from_frames,
    render_economizer_sql,
    rows_to_metrics,
    run_economizer_sql,
)

ROOT = Path(__file__).resolve().parents[1]
H = 3_600_000
T0 = int(pd.Timestamp("2026-04-06", tz="UTC").value // 1_000_000)
COLS = ["equipment_id", "equipment_type", "fan_on_hours", "n_fan_on_samples", "n_identifiable", "has_damper",
        "median_mat_resid_f", "mat_resid_mae_f", "dt_min_f"]


def _postgres_configured() -> bool:
    return bool(os.environ.get("POSTGRES_TEST_URL")) and os.environ.get("OPENFDD_PG_TEST_DISPOSABLE") == "1"


def _frames():
    """A percent damper, a fraction damper with a fan command and missing MAT samples, an RTU with no damper, a VAV."""
    rng = np.random.default_rng(1649)
    idx = pd.date_range("2026-04-06", periods=12 * 24 * 7, freq="5min", tz="UTC")
    h = np.asarray(idx.hour + idx.minute / 60.0, dtype=float)
    oat = 12 + 10 * np.sin((h - 9) / 24 * 2 * np.pi) + rng.normal(0, 0.3, len(idx))
    rat = 22 + rng.normal(0, 0.2, len(idx))
    damper = np.clip(0.2 + 0.6 * (oat < 18), 0, 1)
    mat = rat + damper * (oat - rat) + rng.normal(0, 0.4, len(idx))
    fan = ((h >= 6) & (h < 20)).astype(float)
    mat_holes = mat.copy()
    mat_holes[::7] = np.nan

    def frame(cols, et="AHU"):
        df = pd.DataFrame(cols, index=idx)
        df.attrs["equipment_type"] = et
        return df

    frames = {
        "AHU-1": frame({"f": fan, "o": oat, "r": rat, "m": mat, "d": damper * 100}),
        "AHU-2": frame({"f": fan * 100, "c": fan, "o": oat, "r": rat, "m": mat_holes, "d": damper}),
        "RTU-1": frame({"f": fan, "o": oat, "r": rat, "m": mat}, "RTU"),
        "VAV-1": frame({"f": fan, "o": oat, "r": rat, "m": mat}, "VAV"),
    }
    base = {"fan-status": "f", "outside-air-temp": "o", "return-air-temp": "r", "mixed-air-temp": "m"}
    role_map = {
        "AHU-1": {**base, "outside-air-damper": "d"},
        "AHU-2": {**base, "fan-cmd": "c", "outside-air-damper": "d"},
        "RTU-1": dict(base),
        "VAV-1": dict(base),
    }
    return frames, role_map


def _want(frames, role_map):
    return economizer_free_cooling_diagnostics(frames, role_map)["metrics"][COLS].sort_values("equipment_id"
                                                                                           ).reset_index(drop=True)


def _sorted(df):
    return df[COLS].sort_values("equipment_id").reset_index(drop=True)


def test_packaged_sql_is_the_repo_file():
    repo = (ROOT / "sql" / "analytics" / "economizer_metrics.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert economizer_sql_template().replace("\r\n", "\n") == repo


def test_render_quotes_and_checks():
    sql = render_economizer_sql("sqlite", [("o'ahu", "fan", "k'1")], site_id="s'1", start_ms=1, end_ms=2)
    assert "'o''ahu'" in sql and "'k''1'" in sql and "'s''1'" in sql and "t >= 1" in sql and "{" not in sql
    for bad in ({"engine": "oracle"}, {"engine": "sqlite", "dt_min_c": -1}, {"engine": "sqlite", "max_gap_seconds": 0},
                {"engine": "sqlite", "start_ms": 5, "end_ms": 5}):
        engine = bad.pop("engine")
        with pytest.raises(ValueError):
            render_economizer_sql(engine, [("A", "fan", "k")], **bad)
    with pytest.raises(ValueError):
        render_economizer_sql("sqlite", [("A", "valve", "k")])


@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_matches_pandas(engine):
    if engine == "duckdb":
        pytest.importorskip("duckdb")
    frames, role_map = _frames()
    want = _want(frames, role_map)
    assert list(want["equipment_id"]) == ["AHU-1", "AHU-2", "RTU-1"]  # the VAV is not an economizer unit
    got = _sorted(economizer_metrics_sql(frames, role_map, engine=engine))
    pd.testing.assert_frame_equal(got, want, check_dtype=False)


def _run(samples, roles, **kw):
    points = [{"site_id": "local", "point_key": k, "equipment_id": e, "role": r} for e, r, k in roles]
    conn = sqlite3.connect(":memory:")
    try:
        create_core(conn, "sqlite")
        load_core(conn, "sqlite", points, samples)
        return run_economizer_sql(conn, "sqlite", roles, **kw)
    finally:
        conn.close()


def test_median_damper_scale_and_identifiable_rules():
    roles = [("A", "fan", "f"), ("A", "oat", "o"), ("A", "rat", "r"), ("A", "mat", "m"), ("A", "damper", "d")]
    oat = [30.0, 30.0, 30.0, 30.0, 24.0]  # the last sample is not identifiable (|30 - 20| ok, |24 - 20| < 5.56)
    mat = [21.0, 23.0, 24.0, 28.0, 21.0]
    samples = []
    for i in range(5):
        t = T0 + i * H // 4
        samples += [("local", "f", t, 1.0), ("local", "o", t, oat[i]), ("local", "r", t, 20.0),
                    ("local", "m", t, mat[i]), ("local", "d", t, 20.0)]  # max 20 > 1: the series is percent
    row = _run(samples, roles)[0]
    # damper 0.2: predicted MAT 22.0 when OAT 30; residuals -1, 1, 2, 6 -> median 1.5, MAE 2.5
    assert (row["n_fan_on"], row["n_identifiable"], row["n_resid"]) == (5, 4, 4)
    assert row["median_resid"] == pytest.approx(1.5) and row["mae_resid"] == pytest.approx(2.5)
    assert row["fan_on_ms"] == H  # four 15-minute intervals; the last sample owns 0
    odd = _run([s for s in samples if s[2] != T0 + 3 * H // 4], roles)[0]
    assert odd["median_resid"] == pytest.approx(1.0)  # residuals -1, 1, 2 -> the middle one


def test_fan_never_on_gives_no_row():
    roles = [("A", "fan", "f"), ("A", "oat", "o"), ("A", "rat", "r"), ("A", "mat", "m")]
    samples = [("local", k, T0 + i * H, v) for i in range(3) for k, v in (("f", 0.0), ("o", 30.0), ("r", 20.0), ("m", 25.0))]
    assert _run(samples, roles) == []


@pytest.mark.skipif(not _postgres_configured(), reason="needs POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1")
def test_postgres_economizer_matches_pandas():
    psycopg = pytest.importorskip("psycopg")
    frames, role_map = _frames()
    roles, points, samples, info = plan_from_frames(frames, role_map)
    base = os.environ["POSTGRES_TEST_URL"]
    dbname = f"openfdd_econ_{secrets.token_hex(6)}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{dbname}"')
    try:
        url = urlunparse(urlparse(base)._replace(path=f"/{dbname}"))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            create_core(conn, "postgres")
            load_core(conn, "postgres", points, samples)
            rows = run_economizer_sql(conn, "postgres", roles)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
    pd.testing.assert_frame_equal(_sorted(rows_to_metrics(rows, info)), _want(frames, role_map), check_dtype=False)
