"""SQL mechanical-cooling OAT bins (#1649): sql/analytics/mech_cooling_oat_bins.sql == core.mech_cooling_oat_bins.

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

from open_fdd.analytics.core import mech_cooling_oat_bins  # noqa: E402
from open_fdd.analytics.sql_anomaly import create_core, load_core  # noqa: E402
from open_fdd.analytics.sql_mech_cooling import (  # noqa: E402
    build_plan,
    mech_bins_sql_template,
    mech_cooling_oat_bins_sql,
    plan_from_frames,
    render_mech_bins_sql,
    rows_to_frame,
    run_mech_bins_sql,
)

ROOT = Path(__file__).resolve().parents[1]
H = 3_600_000
T0 = int(pd.Timestamp("2026-07-06", tz="UTC").value // 1_000_000)
COLS = ["equipment_id", "source", "source_kind", "series_kind", "bin_start", "bin_label", "hours", "runtime_hours",
        "valid_elapsed_hours", "coverage_pct", "equipment_type", "cooling_technology", "proof_role", "proof_quality",
        "device_count"]


def _postgres_configured() -> bool:
    return bool(os.environ.get("POSTGRES_TEST_URL")) and os.environ.get("OPENFDD_PG_TEST_DISPOSABLE") == "1"


def _frames():
    """Five devices, one per proof path: chiller status, OR'ed RTU stages, a heat pump gated by cooling mode, an AHU
    whose mapped status never runs (the command wins), and an AHU proven by compressor current."""
    rng = np.random.default_rng(1649)
    idx = pd.date_range("2026-07-06", periods=12 * 24 * 10, freq="5min", tz="UTC")
    hours = idx.hour + idx.minute / 60.0
    oat = 18.0 + 14.0 * np.sin((hours - 9) / 24 * 2 * np.pi) + rng.normal(0, 0.5, len(idx))
    busy = (oat > 22).astype(float)

    def frame(cols, et):
        df = pd.DataFrame(cols, index=idx)
        df.attrs["equipment_type"] = et
        return df

    frames = {
        "CH-1": frame({"ch_s": busy, "oat": oat}, "CHW_PLANT"),
        "RTU-1": frame({"s1": (oat > 24).astype(float), "s2": (oat > 28).astype(float), "oat": oat}, "RTU"),
        "HP-1": frame({"comp": (rng.random(len(idx)) > 0.5).astype(float), "mode": busy, "oat": oat}, "HP"),
        "AHU-1": frame({"cs": np.zeros(len(idx)), "cc": busy * 100.0, "oat": oat}, "AHU"),
        "AHU-2": frame({"amps": np.where(busy > 0, 12.0, 0.4), "oat": oat}, "AHU"),
    }
    role_map = {
        "CH-1": {"chiller_operating_status": "ch_s", "outdoor_air_intake_temperature": "oat"},
        "RTU-1": {"compressor-stage-1": "s1", "compressor-stage-2": "s2", "outdoor_air_intake_temperature": "oat"},
        "HP-1": {"compressor_operating_status": "comp", "heat-pump-cooling-status": "mode", "outdoor_air_intake_temperature": "oat"},
        "AHU-1": {"compressor_operating_status": "cs", "compressor-cmd": "cc", "outdoor_air_intake_temperature": "oat"},
        "AHU-2": {"compressor-current": "amps", "outdoor_air_intake_temperature": "oat"},
    }
    return frames, role_map


def _sorted(df):
    return df[COLS].sort_values(["equipment_id", "bin_start"]).reset_index(drop=True)


def test_packaged_sql_is_the_repo_file():
    repo = (ROOT / "sql" / "analytics" / "mech_cooling_oat_bins.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert mech_bins_sql_template().replace("\r\n", "\n") == repo


def test_render_quotes_and_checks():
    plan = build_plan([("o'ahu", "AHU", {"compressor_operating_status": "k'1", "outdoor_air_intake_temperature": "oat"})])
    sql = render_mech_bins_sql("sqlite", plan, site_id="s'1", start_ms=1, end_ms=2)
    assert "'o''ahu'" in sql and "'k''1'" in sql and "'s''1'" in sql and "t >= 1" in sql and "{" not in sql
    empty = render_mech_bins_sql("duckdb", build_plan([]))
    assert "WHERE 1 = 0" in empty
    for bad in ({"engine": "oracle"}, {"engine": "sqlite", "max_gap_seconds": 0},
                {"engine": "sqlite", "start_ms": 5, "end_ms": 5}):
        engine = bad.pop("engine")
        with pytest.raises(ValueError):
            render_mech_bins_sql(engine, plan, **bad)


def test_plan_follows_the_pandas_ladder():
    # a heat pump without a cooling-mode role, and a VAV, are not cooling devices
    assert build_plan([("HP-9", "HP", {"compressor_operating_status": "a"}), ("VAV-1", "VAV", {"compressor_operating_status": "b"})]
                      ).candidates == []
    plan = build_plan([("CH-1", "CHW_PLANT", {"compressor_operating_status": "cs", "chiller_electric_current": "amps"})])
    assert [(r[1], r[2], r[3], r[4], r[5]) for r in plan.candidates] == [(1, 1, "cs", "on", None),
                                                                        (3, 0, "amps", "above", 5.0)]
    stages = build_plan([("RTU-1", "RTU", {"compressor-stage-1": "s1", "dx-stage": "s4"})])
    assert {(r[1], r[2], r[3]) for r in stages.candidates} == {(3, 0, "s1"), (3, 0, "s4")}
    assert stages.labels[("RTU-1", 3, 0)] == ("compressor-stage", "ahu_dx", "direct")


@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_matches_pandas(engine):
    if engine == "duckdb":
        pytest.importorskip("duckdb")
    frames, role_map = _frames()
    want = mech_cooling_oat_bins(frames, role_map)
    want = _sorted(want[want["series_kind"] == "individual_device"])
    got = _sorted(mech_cooling_oat_bins_sql(frames, role_map, engine=engine))
    assert set(want["equipment_id"]) == {"CH-1", "RTU-1", "HP-1", "AHU-1", "AHU-2"}
    assert set(got.loc[got["equipment_id"] == "AHU-1", "proof_role"]) == {"compressor-cmd"}
    pd.testing.assert_frame_equal(got, want, check_dtype=False)


def _run(points, samples, devices, **kw):
    conn = sqlite3.connect(":memory:")
    try:
        create_core(conn, "sqlite")
        load_core(conn, "sqlite", points, samples)
        return run_mech_bins_sql(conn, "sqlite", build_plan(devices), **kw)
    finally:
        conn.close()


def _pts(*keys):
    return [{"site_id": "local", "point_key": k, "equipment_id": "AHU-1", "role": k} for k in keys]


def test_gap_and_oat_as_of_rules():
    # proof every 30 min; OAT only on the hour (as-of fills the half hours); a 2 h hole is unknown
    times = [T0 + i * H // 2 for i in range(6)] + [T0 + 5 * H // 2 + 2 * H + 1]
    samples = [("local", "cs", t, 1.0) for t in times]
    samples += [("local", "oat", T0 + i * H, 25.0) for i in range(3)]
    rows = _run(_pts("cs", "oat"), samples, [("AHU-1", "AHU", {"compressor_operating_status": "cs", "outdoor_air_intake_temperature": "oat"})])
    assert len(rows) == 1 and rows[0]["bin_label"] == "21-27"
    assert rows[0]["on_ms"] == 5 * H // 2  # five half-hour intervals; the 2 h + 1 ms hole counts 0
    assert rows[0]["valid_ms"] == 5 * H // 2 and rows[0]["span_ms"] == times[-1] - T0


def test_no_oat_or_never_on_gives_no_rows():
    samples = [("local", "cs", T0 + i * H // 2, 1.0) for i in range(4)]
    assert _run(_pts("cs"), samples, [("AHU-1", "AHU", {"compressor_operating_status": "cs"})]) == []
    off = [("local", "cs", T0 + i * H // 2, 0.0) for i in range(4)] + [("local", "oat", T0, 30.0)]
    assert _run(_pts("cs", "oat"), off, [("AHU-1", "AHU", {"compressor_operating_status": "cs", "outdoor_air_intake_temperature": "oat"})]) == []


@pytest.mark.skipif(not _postgres_configured(), reason="needs POSTGRES_TEST_URL and OPENFDD_PG_TEST_DISPOSABLE=1")
def test_postgres_mech_bins_match_pandas():
    psycopg = pytest.importorskip("psycopg")
    frames, role_map = _frames()
    want = mech_cooling_oat_bins(frames, role_map)
    want = _sorted(want[want["series_kind"] == "individual_device"])
    plan, points, samples, types = plan_from_frames(frames, role_map)
    base = os.environ["POSTGRES_TEST_URL"]
    dbname = f"openfdd_mech_{secrets.token_hex(6)}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{dbname}"')
    try:
        url = urlunparse(urlparse(base)._replace(path=f"/{dbname}"))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            create_core(conn, "postgres")
            load_core(conn, "postgres", points, samples)
            rows = run_mech_bins_sql(conn, "postgres", plan)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
    pd.testing.assert_frame_equal(_sorted(rows_to_frame(rows, types)), want, check_dtype=False)
