"""SQL weekly motor run hours (#1649): sql/analytics/motor_weekly_runtime.sql == core.motor_run_hours_weekly.

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

from open_fdd.analytics.core import motor_run_hours_weekly  # noqa: E402
from open_fdd.analytics.sql_anomaly import create_core, load_core  # noqa: E402
from open_fdd.analytics.sql_runtime import (  # noqa: E402
    _core_from_frames,
    _ms,
    motor_run_hours_weekly_sql,
    render_runtime_sql,
    run_runtime_sql,
    runtime_sql_template,
)

ROOT = Path(__file__).resolve().parents[1]
MS = 1000
H = 3_600_000
MON = pd.Timestamp("2026-03-02", tz="UTC")  # a Monday
T0 = int(MON.value // 1_000_000)
COMPARE = ["week_start", "week_label", "equipment_id", "signal", "motor_kind", "plant_group", "hours", "avg_oat_c",
           "partial_week"]


def _postgres_configured() -> bool:
    return bool(os.environ.get("POSTGRES_TEST_URL")) and os.environ.get("OPENFDD_PG_TEST_DISPOSABLE") == "1"


def _frames():
    """An AHU (status and command, a 2 h hole), a boiler pump in percent, a chilled-water plant pump with a status."""
    rng = np.random.default_rng(1649)
    idx = pd.date_range(MON, periods=12 * 24 * 17, freq="5min")
    hour = idx.hour
    fan = ((hour >= 6) & (hour < 18)).astype(float)
    oat = 10.0 + 8.0 * np.sin(np.arange(len(idx)) / 288.0 * 2 * np.pi)
    ahu = pd.DataFrame({"sf_status": fan, "sf_cmd": np.roll(fan, 3), "oat": oat}, index=idx)
    ahu = ahu.drop(ahu.index[(ahu.index >= "2026-03-04 08:00") & (ahu.index < "2026-03-04 10:00")])
    ahu.attrs["equipment_type"] = "AHU"
    hw = pd.DataFrame({"p1": (rng.random(len(idx)) > 0.4).astype(float) * 100.0, "wx": oat + 1.5}, index=idx)
    hw.attrs["equipment_type"] = "BOILER"
    chw_on = (rng.random(len(idx)) > 0.3).astype(float)
    chw = pd.DataFrame({"pmp_s": chw_on, "pmp_c": np.ones(len(idx))}, index=idx)
    chw.attrs["equipment_type"] = "CHW_PLANT"
    frames = {"AHU-1": ahu, "HW-1": hw, "CHW-1": chw}
    role_map = {
        "AHU-1": {"fan-status": "sf_status", "fan-cmd": "sf_cmd", "outside-air-temp": "oat"},
        "HW-1": {"hw-pump-cmd": "p1", "web-outside-air-temp": "wx"},
        "CHW-1": {"chw-pump-status": "pmp_s", "chw-pump-cmd": "pmp_c"},
    }
    return frames, role_map


def _pandas_reference(frames, role_map):
    want = motor_run_hours_weekly(frames, role_map, include_all_mapped=True)
    # Plant discovery may add series the SQL never reads (a chiller "on" derived from temperatures, named towers);
    # the SQL contract is bound fan / pump roles only.
    want = want[want["signal"].isin(["fan-status", "fan-cmd", "pump-status", "pump-cmd", "chw-pump-status",
                                     "chw-pump-cmd", "hw-pump-cmd"])]
    return want


def _sorted(df):
    return df[COMPARE].sort_values(["equipment_id", "signal", "week_start"]).reset_index(drop=True)


def test_packaged_sql_is_the_repo_file():
    repo = (ROOT / "sql" / "analytics" / "motor_weekly_runtime.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert runtime_sql_template().replace("\r\n", "\n") == repo


def test_render_checks_inputs():
    sql = render_runtime_sql("sqlite", site_id="o'brien", equipment_ids=["a'b"], start_ms=10, end_ms=20)
    assert "'o''brien'" in sql and "'a''b'" in sql and "t >= 10" in sql and "t < 20" in sql
    assert "{" not in sql and "3600000" in sql
    assert "epoch_ms(s.ts)" in render_runtime_sql("duckdb")
    assert "EXTRACT(EPOCH FROM s.ts)" in render_runtime_sql("postgres")
    for bad in ({"engine": "oracle"}, {"engine": "sqlite", "max_gap_seconds": 0},
                {"engine": "sqlite", "max_gap_seconds": float("inf")},
                {"engine": "sqlite", "start_ms": 5, "end_ms": 5}):
        with pytest.raises(ValueError):
            render_runtime_sql(**bad)


@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_matches_pandas(engine):
    if engine == "duckdb":
        pytest.importorskip("duckdb")
    frames, role_map = _frames()
    got = _sorted(motor_run_hours_weekly_sql(frames, role_map, engine=engine))
    want = _sorted(_pandas_reference(frames, role_map))
    assert len(want) == 9  # 3 motors x 3 weeks
    pd.testing.assert_frame_equal(got, want, check_dtype=False)


def _run(points, samples, **kw):
    conn = sqlite3.connect(":memory:")
    try:
        create_core(conn, "sqlite")
        load_core(conn, "sqlite", points, samples)
        return run_runtime_sql(conn, "sqlite", **kw)
    finally:
        conn.close()


def _pt(key, eq, role):
    return {"site_id": "local", "point_key": key, "equipment_id": eq, "role": role}


def _series(key, start, n, step_ms, value):
    return [("local", key, start + i * step_ms, float(value(i) if callable(value) else value)) for i in range(n)]


def test_status_beats_command_and_ambiguous_roles_are_left_out():
    points = [_pt("s", "AHU-1", "fan_status"), _pt("c", "AHU-1", "fan_cmd"),
              _pt("x1", "AHU-2", "fan_status"), _pt("x2", "AHU-2", "fan_status")]
    samples = (_series("s", T0, 13, 300 * MS, 1) + _series("c", T0, 13, 300 * MS, 0)
               + _series("x1", T0, 13, 300 * MS, 1) + _series("x2", T0, 13, 300 * MS, 1))
    rows = _run(points, samples)
    assert [(r["equipment_id"], r["signal"]) for r in rows] == [("AHU-1", "fan_status")]
    assert rows[0]["run_hours"] == pytest.approx(1.0)  # 12 intervals of 5 min; the last sample owns 0


def test_gap_cap_is_inclusive_and_longer_gaps_count_zero():
    points = [_pt("p", "P-1", "pump_cmd")]
    times = [T0, T0 + H, T0 + 2 * H + 1]  # exactly 1 h counts; 1 h + 1 ms is unknown
    rows = _run(points, [("local", "p", t, 1.0) for t in times])
    assert rows[0]["run_hours"] == pytest.approx(1.0)


def test_percent_values_and_threshold():
    points = [_pt("p", "P-1", "pump_cmd")]
    vals = [100.0, 4.0, 0.06, 0.05, 1.0]  # 4 % is off, 0.06 is on, 0.05 is not above the threshold
    rows = _run(points, [("local", "p", T0 + i * H, v) for i, v in enumerate(vals)])
    assert rows[0]["run_hours"] == pytest.approx(2.0)


def test_intervals_book_to_the_starting_week_and_partial_weeks():
    points = [_pt("f", "AHU-1", "fan_status")]
    sunday_late = T0 + 7 * 24 * H - H // 2  # Sunday 23:30, the interval runs into Monday
    samples = [("local", "f", T0, 1.0), ("local", "f", T0 + H // 2, 0.0),
               ("local", "f", sunday_late, 1.0), ("local", "f", sunday_late + H, 1.0)]
    rows = _run(points, samples)
    assert [r["week_start_ms"] for r in rows] == [T0]
    assert rows[0]["run_hours"] == pytest.approx(1.5)
    assert rows[0]["partial_week"] is False  # the week's samples span 6 days 23.5 h


def test_window_bounds_the_samples():
    points = [_pt("f", "AHU-1", "fan_status")]
    samples = _series("f", T0, 25, H // 2, 1)  # 12 h of half-hour samples
    rows = _run(points, samples, start_ms=T0 + 2 * H, end_ms=T0 + 4 * H)
    assert rows[0]["run_hours"] == pytest.approx(1.5)  # samples at 2.0 .. 3.5 h; the last one owns 0
    assert rows[0]["partial_week"] is True


def test_avg_oat_is_the_as_of_reading_over_on_intervals():
    points = [_pt("f", "AHU-1", "fan_status"), _pt("o", "AHU-1", "outside_air_temp")]
    samples = [("local", "f", T0 + i * H // 2, v) for i, v in enumerate([1, 1, 0, 1, 1])]
    samples += [("local", "o", T0, 10.0), ("local", "o", T0 + H, 20.0)]  # hourly OAT, carried to the half hours
    rows = _run(points, samples, oats=[("AHU-1", "o")])
    # ON intervals start at 0.0 h (OAT 10), 0.5 h (10, carried) and 1.5 h (20, carried); the 2.0 h sample owns 0
    assert rows[0]["run_hours"] == pytest.approx(1.5)
    assert rows[0]["avg_oat_c"] == pytest.approx((10.0 + 10.0 + 20.0) / 3)
    assert _run(points, samples)[0]["avg_oat_c"] is None  # no OAT point bound


def test_no_motor_roles_gives_no_rows():
    frames = {"AHU-1": pd.DataFrame({"sat": [12.0, 13.0]}, index=pd.date_range(MON, periods=2, freq="5min"))}
    out = motor_run_hours_weekly_sql(frames, {"AHU-1": {"sat": "sat"}})
    assert out.empty and list(out.columns)[:2] == ["week_start", "week_label"]


def _local_weeks_and_schedule(tz="America/Chicago"):
    """Local Monday boundaries (the week of 2026-03-08 is 167 h: DST starts) and weekday 07:00-18:00 local occupancy."""
    days = pd.date_range("2026-02-23", "2026-03-24", freq="D", tz=tz)
    starts = [d for d in days if d.dayofweek == 0]
    occ = [(d + pd.Timedelta(hours=7), d + pd.Timedelta(hours=18)) for d in days if d.dayofweek < 5]
    return starts, occ


@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_local_weeks_and_occupancy_match_pandas(engine):
    if engine == "duckdb":
        pytest.importorskip("duckdb")
    frames, role_map = _frames()
    starts, occ = _local_weeks_and_schedule()
    kw = {"week_starts": starts, "occupied_intervals": occ}
    cols = COMPARE + ["in_hours", "after_hours"]
    want = _pandas_reference_kw(frames, role_map, **kw)[cols]
    got = motor_run_hours_weekly_sql(frames, role_map, engine=engine, **kw)[cols]
    order = ["equipment_id", "signal", "week_start"]
    want = want.sort_values(order).reset_index(drop=True)
    got = got.sort_values(order).reset_index(drop=True)
    pd.testing.assert_frame_equal(got, want, check_dtype=False)
    # local Monday 00:00 Chicago is 06:00 UTC in February and 05:00 UTC after the DST change
    assert {w.hour for w in got["week_start"]} == {5, 6}
    assert set(got["week_label"]) <= {d.strftime("%Y-%m-%d") for d in starts}
    # the frames start Monday 00:00 UTC, which is Sunday evening in Chicago: that slice is the local week of Feb 23 and
    # is all after-hours; every full local week has both
    first = got["week_label"] == "2026-02-23"
    assert (got.loc[first, "in_hours"] == 0).all() and (got.loc[~first, "in_hours"] > 0).all()
    assert (got["after_hours"] > 0).all()
    assert ((got["in_hours"] + got["after_hours"]) - got["hours"]).abs().max() <= 0.011


def test_custom_weeks_drop_samples_before_the_first_boundary():
    points = [_pt("f", "AHU-1", "fan_status")]
    samples = _series("f", T0, 25, H // 2, 1)
    rows = _run(points, samples, weeks=[("AHU-1", T0 + 6 * H)])
    assert [r["week_start_ms"] for r in rows] == [T0 + 6 * H]
    assert rows[0]["run_hours"] == pytest.approx(6.0)  # 6 h .. 12 h; the last sample owns 0
    assert rows[0]["in_hours"] is None
    occ = _run(points, samples, occupied=[("AHU-1", T0, T0 + 3 * H)])
    assert occ[0]["in_hours"] == pytest.approx(3.0) and occ[0]["run_hours"] == pytest.approx(12.0)


def _pandas_reference_kw(frames, role_map, **kw):
    want = motor_run_hours_weekly(frames, role_map, include_all_mapped=True, **kw)
    return want[want["signal"].isin(["fan-status", "fan-cmd", "pump-status", "pump-cmd", "chw-pump-status",
                                      "chw-pump-cmd", "hw-pump-cmd"])]


@pytest.mark.skipif(not _postgres_configured(), reason="needs POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1")
def test_postgres_matches_sqlite():
    psycopg = pytest.importorskip("psycopg")
    frames, role_map = _frames()
    points, samples, oats = _core_from_frames(frames, role_map)
    starts, occ = _local_weeks_and_schedule()
    kw = {"oats": oats, "weeks": [(e, _ms(w)) for e in frames for w in starts],
          "occupied": [(e, _ms(x), _ms(y)) for e in frames for x, y in occ]}
    lite = _run(points, samples, **kw)
    base = os.environ["POSTGRES_TEST_URL"]
    dbname = f"openfdd_runtime_{secrets.token_hex(6)}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{dbname}"')
    try:
        url = urlunparse(urlparse(base)._replace(path=f"/{dbname}"))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            create_core(conn, "postgres")
            load_core(conn, "postgres", points, samples)
            rows = run_runtime_sql(conn, "postgres", **kw)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
    assert len(rows) == len(lite) > 0
    for a, b in zip(rows, lite):
        assert {k: a[k] for k in a if k not in ("run_hours", "avg_oat_c")} == {k: b[k] for k in b if k not in ("run_hours", "avg_oat_c")}
        assert a["run_hours"] == pytest.approx(b["run_hours"], abs=1e-9)
        assert (a["avg_oat_c"] is None) == (b["avg_oat_c"] is None)
        if a["avg_oat_c"] is not None:
            assert a["avg_oat_c"] == pytest.approx(b["avg_oat_c"], abs=1e-9)
