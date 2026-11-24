"""Fault-confidence screen: synthetic planted cases, Open-FDD results layout, portable SQL on several engines."""

from __future__ import annotations

import json
import os
import sqlite3

import numpy as np
import pandas as pd
import pytest

from open_fdd.ml.confidence import (
    ConfidenceConfig,
    _co_rules,
    history_evidence,
    main,
    screen,
    screen_sql,
    summarize,
)
from open_fdd.ml.confidence_report import build_report, to_markdown
from open_fdd.ml.confidence_sql import HistoryMap, SourceMap, ident


def _fixture(seed: int = 7, units: int = 6) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generic units, 4 days at 15 min. Planted cases:

    * EQ-1: real supply-temperature fault: large, persistent excursion, abnormal inputs, a second rule co-faults.
    * EQ-2: false positive: the sensor goes stale during the episode and the unit is not running.
    * every unit: rule R-TIGHT has a threshold inside normal noise, so it fires everywhere (review).
    """
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-01-01", periods=4 * 96, freq="15min", tz="UTC")
    flags, hist = [], []
    for u in range(1, units + 1):
        eq = f"EQ-{u}"
        sat = 13.0 + rng.normal(0, 0.4, ts.size)
        running = np.ones(ts.size, dtype=int)
        if u == 1:
            sat[150:190] += 6.0
        if u == 2:
            sat[200:216] = sat[199] + 2.5
            running[200:216] = 0
        for i, t in enumerate(ts):
            hist.append((t, eq, "supply_air_temp", sat[i]))
            hist.append((t, eq, "fan_status", float(running[i])))
            flags.append((t, eq, "R-SAT-HIGH", int(sat[i] > 15.0), sat[i], 15.0, running[i]))
            flags.append((t, eq, "R-TIGHT", int(sat[i] > 13.2), sat[i], 13.2, running[i]))
            flags.append((t, eq, "R-COIL", int(u == 1 and 150 <= i < 190), np.nan, np.nan, running[i]))
    fl = pd.DataFrame(flags, columns=["timestamp", "equipment_id", "rule_id", "flag", "value", "threshold", "running"])
    hs = pd.DataFrame(hist, columns=["timestamp", "equipment_id", "point_id", "value"])
    return fl, hs


def _longest(ep: pd.DataFrame, eq: str, rule: str) -> pd.Series:
    return ep[(ep["equipment_id"] == eq) & (ep["rule_id"] == rule)].sort_values("duration_h").iloc[-1]


# --------------------------------------------------------------------------- behaviour


def test_scoring_separates_planted_cases():
    fl, hs = _fixture()
    res = screen(fl, hs)
    ep = res["episodes"]
    real, fp = _longest(ep, "EQ-1", "R-SAT-HIGH"), _longest(ep, "EQ-2", "R-SAT-HIGH")
    assert real["label"] == "likely_real", real["reason"]
    assert fp["label"] == "likely_false_positive", fp["reason"]
    assert real["p_real"] > fp["p_real"] + 0.3
    assert (ep.loc[ep["rule_id"] == "R-TIGHT", "label"] == "tuning_suggested").mean() >= 0.6
    rules = res["rules"].set_index("rule_id")
    assert rules.loc["R-TIGHT", "suggestion"] == "review threshold or applicability"
    eqh = res["equipment"].set_index("equipment_id")
    assert eqh.loc["EQ-1", "rules_likely_real"] >= 1
    assert eqh.loc["EQ-1", "likely_real"] > eqh.loc["EQ-3", "likely_real"]


def test_probabilities_sum_to_one_and_reasons_present():
    fl, hs = _fixture(seed=11)
    ep = screen(fl, hs)["episodes"]
    assert np.allclose(ep[["p_real", "p_false_positive", "p_tuning"]].sum(axis=1), 1.0, atol=0.01)
    assert ep["reason"].str.len().min() > 0


def test_episodes_merge_small_gaps():
    ts = pd.date_range("2026-01-01", periods=8, freq="15min", tz="UTC")
    fl = pd.DataFrame({"timestamp": ts, "equipment_id": "A", "rule_id": "R", "flag": [0, 1, 1, 0, 1, 0, 0, 1]})
    assert len(screen(fl, config=ConfidenceConfig(gap_samples=1))["episodes"]) == 2
    assert len(screen(fl, config=ConfidenceConfig(gap_samples=0))["episodes"]) == 3


def test_flag_text_and_bool_inputs():
    ts = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
    fl = pd.DataFrame({"timestamp": ts, "equipment_id": "A", "rule_id": "R", "flag": ["FAULT", "PASS", "true", "PASS"]})
    ep = screen(fl, config=ConfidenceConfig(gap_samples=0))["episodes"]
    assert ep["n_samples"].tolist() == [1, 1]


def test_mixed_iso_timestamps_are_accepted():
    fl = pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T00:15:00.250Z", "2026-01-01T00:30:00+00:00"],
                       "equipment_id": "A", "rule_id": "R", "flag": [1, 1, 0]})
    ep = screen(fl)["episodes"]
    assert len(ep) == 1 and ep.iloc[0]["n_samples"] == 2


def test_missing_columns_raise():
    with pytest.raises(ValueError, match="missing"):
        screen(pd.DataFrame({"timestamp": [], "rule_id": []}))


def test_works_without_history_or_optional_columns():
    fl, _ = _fixture()
    res = screen(fl[["timestamp", "equipment_id", "rule_id", "flag"]])
    assert len(res["episodes"]) > 0
    s = summarize(res)
    assert s["episodes"] == len(res["episodes"])
    assert "input data quality not assessed" in res["episodes"]["reason"].iloc[0]


def test_screen_does_not_mutate_inputs():
    fl, hs = _fixture()
    before = fl.copy()
    screen(fl, hs)
    pd.testing.assert_frame_equal(fl, before)


def test_data_quality_rule_is_confirmed_and_rolls_up_as_data_issue():
    fl, hs = _fixture()
    fl = fl[fl["rule_id"] != "R-TIGHT"]
    dq = fl[fl["rule_id"] == "R-SAT-HIGH"].copy()
    dq["rule_id"] = "DQ-STALE"
    dq["flag"] = 0
    dq.loc[dq.index[dq["equipment_id"] == "EQ-2"][200:216], "flag"] = 1
    dq = dq.drop(columns=["value", "threshold"])
    res = screen(pd.concat([fl, dq], ignore_index=True), hs, ConfidenceConfig(data_quality_rules=("DQ-",)))
    row = res["episodes"][res["episodes"]["rule_id"] == "DQ-STALE"].iloc[0]
    assert row["label"] == "likely_real", row["reason"]
    assert "data-quality rule confirmed" in row["reason"]
    eqh = res["equipment"].set_index("equipment_id")
    assert eqh.loc["EQ-2", "health"] == "sensor or data issue"
    assert eqh.loc["EQ-1", "health"] in {"equipment issue likely", "check equipment"}


# --------------------------------------------------------------------------- history evidence edge cases


def _hist(values, start="2026-01-01", freq="15min", point="p", kind=None):
    ts = pd.date_range(start, periods=len(values), freq=freq, tz="UTC")
    return pd.DataFrame({"ts": ts, "point_id": point, "value": values, "kind": kind})


def test_constant_status_point_is_not_stale():
    h = _hist([1.0] * 200, point="fan_status")
    ev = history_evidence(h, h["ts"].iloc[50], h["ts"].iloc[66], ConfidenceConfig())
    assert np.isnan(ev["dq_stale"])


def test_short_constant_window_needs_stale_run():
    rng = np.random.default_rng(0)
    vals = list(13 + rng.normal(0, 0.3, 100))
    vals[50] = vals[51] = 14.0
    h = _hist(vals)
    ev = history_evidence(h, h["ts"].iloc[50], h["ts"].iloc[51], ConfidenceConfig(stale_run=6))
    assert np.isnan(ev["dq_stale"]) or ev["dq_stale"] == 0.0


def test_absent_timestamps_count_as_gaps():
    rng = np.random.default_rng(1)
    h = _hist(list(13 + rng.normal(0, 0.3, 200)))
    start, end = h["ts"].iloc[100], h["ts"].iloc[104]
    h = h.drop(index=[101, 102, 103])
    ev = history_evidence(h, start, end, ConfidenceConfig())
    assert ev["dq_gap"] == pytest.approx(0.6, abs=0.01)


def test_configured_interval_scores_gaps_with_few_readings():
    h = _hist([13.0, 13.4], freq="60min")
    ev = history_evidence(h, h["ts"].iloc[0], h["ts"].iloc[1], ConfidenceConfig(expected_interval_s=900))
    assert ev["dq_gap"] == pytest.approx(0.6, abs=0.01)


def test_irregular_event_history_is_not_called_a_gap():
    rng = np.random.default_rng(2)
    offsets = np.cumsum(rng.exponential(600, 200))
    ts = pd.Timestamp("2026-01-01", tz="UTC") + pd.to_timedelta(offsets, unit="s")
    h = pd.DataFrame({"ts": ts, "point_id": "p", "value": rng.normal(0, 1, 200), "kind": None})
    ev = history_evidence(h, ts[100], ts[110], ConfidenceConfig())
    assert np.isnan(ev["dq_gap"])


# --------------------------------------------------------------------------- Open-FDD results layout


def _results_rows() -> pd.DataFrame:
    rows = []
    start = pd.Timestamp("2026-02-01", tz="UTC")
    for u in range(1, 5):
        for d in range(10):
            ws = start + pd.Timedelta(days=d)
            st = "FAULT" if (u == 1 and 3 <= d < 7) or d == 9 else ("INCONCLUSIVE" if d == 5 and u == 2 else "PASS")
            rows.append({"site_id": "S", "equipment_id": f"U{u}", "rule_id": "RULE-A", "subject_key": "",
                         "window_start": ws, "window_end": ws + pd.Timedelta(days=1), "status": st,
                         "fault_hours": 20.0 if st == "FAULT" else (0.0 if st == "PASS" else None),
                         "covered_hours": 24.0 if st != "INCONCLUSIVE" else None})
    return pd.DataFrame(rows)


def test_results_layout_merges_consecutive_fault_windows():
    res = screen(results=_results_rows())
    ep = res["episodes"]
    u1 = ep[ep["equipment_id"] == "U1"].sort_values("start")
    assert len(u1) == 2
    assert u1.iloc[0]["duration_h"] == pytest.approx(96.0)
    assert u1.iloc[0]["persistence"] == pytest.approx(20 / 24)
    rules = res["rules"].set_index("rule_id")
    assert int(rules.loc["RULE-A", "n_unassessed"]) == 1
    assert rules.loc["RULE-A", "fires_on_share"] == 1.0


def test_all_clear_cli_writes_report(tmp_path):
    df = _results_rows()
    df["status"] = "PASS"
    df.to_csv(tmp_path / "r.csv", index=False)
    assert main(["--results", str(tmp_path / "r.csv"), "--out-dir", str(tmp_path / "o"), "--print", "none"]) == 0
    rep = json.loads((tmp_path / "o" / "report.json").read_text())
    assert rep["totals"]["episodes"] == 0
    assert rep["next_checks"] == ["No faults need attention in this window."]
    rules = pd.read_csv(tmp_path / "o" / "rules.csv")
    assert set(rules["suggestion"]) == {"no faults"}


# --------------------------------------------------------------------------- portable SQL across engines


def _load_sql(conn, engine: str, fl: pd.DataFrame, hs: pd.DataFrame, flags_table: str, cols: dict[str, str]) -> None:
    ts_type = {"sqlite": "TEXT", "duckdb": "TIMESTAMPTZ", "postgres": "TIMESTAMPTZ"}[engine]
    cur = conn.cursor()
    c = cols
    cur.execute(f"CREATE TABLE {flags_table} ({c['timestamp']} {ts_type}, {c['equipment_id']} TEXT, {c['rule_id']} TEXT, "
                f"{c['flag']} INTEGER, {c['value']} DOUBLE PRECISION, {c['threshold']} DOUBLE PRECISION, {c['running']} INTEGER)")
    cur.execute(f"CREATE TABLE hist (ts {ts_type}, equipment_id TEXT, point_key TEXT, value DOUBLE PRECISION)")
    ph = "%s" if engine == "postgres" else "?"
    as_ts = (lambda s: s.dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")) if engine == "sqlite" else (lambda s: list(s.dt.to_pydatetime()))
    f = fl.copy()
    rows = list(zip(as_ts(f["timestamp"]), f["equipment_id"], f["rule_id"], f["flag"].astype(int),
                    _none(f["value"]), _none(f["threshold"]),
                    f["running"].astype(int)))
    cur.executemany(f"INSERT INTO {flags_table} VALUES ({', '.join([ph] * 7)})", rows)
    hrows = list(zip(as_ts(hs["timestamp"]), hs["equipment_id"], hs["point_id"], hs["value"]))
    cur.executemany(f"INSERT INTO hist VALUES ({ph}, {ph}, {ph}, {ph})", hrows)
    conn.commit()


def _none(s: pd.Series) -> list:
    return [None if pd.isna(x) else float(x) for x in s]


def _engines():
    out = ["sqlite"]
    try:
        import duckdb  # noqa: F401

        out.append("duckdb")
    except ImportError:
        pass
    if os.environ.get("OPENFDD_TEST_PG_DSN"):
        out.append("postgres")
    return out


def _connect(engine: str, tmp_path):
    if engine == "sqlite":
        return sqlite3.connect(tmp_path / "t.db")
    if engine == "duckdb":
        import duckdb

        return duckdb.connect(str(tmp_path / "t.duckdb"))
    import psycopg

    conn = psycopg.connect(os.environ["OPENFDD_TEST_PG_DSN"])
    schema = f"t_{os.getpid()}_{abs(hash(str(tmp_path))) % 10**6}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    return conn


@pytest.mark.parametrize("engine", _engines())
def test_sql_engines_match_pandas_path_with_custom_schema(engine, tmp_path):
    fl, hs = _fixture(units=4)
    cols = {"timestamp": "ts_utc", "equipment_id": "equip", "rule_id": "rule", "flag": "is_fault",
            "value": "val", "threshold": "lim", "running": "fan_on"}
    conn = _connect(engine, tmp_path)
    try:
        _load_sql(conn, engine, fl, hs, "my_flags", cols)
        src = SourceMap.for_flags("my_flags", columns={**cols, "site_id": ""})
        hm = HistoryMap(table="hist", point_table="", columns={"ts": "ts"})
        got = screen_sql(conn, src, hm)
    finally:
        conn.close()
    ref = screen(fl, hs)
    key = ["equipment_id", "rule_id", "start"]
    a = got["episodes"].sort_values(key).reset_index(drop=True)
    b = ref["episodes"].sort_values(key).reset_index(drop=True)
    assert len(a) == len(b)
    assert (a["label"] == b["label"]).all()
    np.testing.assert_allclose(a["p_real"], b["p_real"], atol=1e-3)
    np.testing.assert_allclose(a["n_samples"], b["n_samples"])


@pytest.mark.parametrize("engine", _engines())
def test_default_open_fdd_schema_on_each_engine(engine, tmp_path):
    """Default names: fdd.rule_result, fdd.point, fdd.input_sample (SQLite: a database attached as ``fdd``)."""
    df = _results_rows()
    conn = _connect(engine, tmp_path)
    created_pg_schema = False
    ts_type = "TEXT" if engine == "sqlite" else "TIMESTAMPTZ"
    ph = "%s" if engine == "postgres" else "?"
    try:
        cur = conn.cursor()
        if engine == "postgres":
            # never touch a real Open-FDD schema: run only where fdd does not exist yet, and drop only what we made
            cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'fdd'")
            if cur.fetchone():
                pytest.skip("schema fdd already exists in the test database; use a disposable database")
            created_pg_schema = True
        if engine == "sqlite":
            cur.execute(f"ATTACH DATABASE '{(tmp_path / 'fdd.db').as_posix()}' AS fdd")
        else:
            cur.execute("CREATE SCHEMA IF NOT EXISTS fdd")
        cur.execute(f"CREATE TABLE fdd.rule_result (site_id TEXT, equipment_id TEXT, rule_id TEXT, subject_key TEXT, "
                    f"window_start {ts_type}, window_end {ts_type}, status TEXT, fault_hours DOUBLE PRECISION, "
                    "covered_hours DOUBLE PRECISION)")
        cur.execute("CREATE TABLE fdd.point (site_id TEXT, point_key TEXT, equipment_id TEXT, role TEXT, kind TEXT)")
        cur.execute(f"CREATE TABLE fdd.input_sample (site_id TEXT, point_key TEXT, ts {ts_type}, value DOUBLE PRECISION)")
        conv = (lambda t: t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")) if engine == "sqlite" else (lambda t: t.to_pydatetime())
        rows = [(r.site_id, r.equipment_id, r.rule_id, r.subject_key, conv(r.window_start), conv(r.window_end), r.status,
                 None if pd.isna(r.fault_hours) else r.fault_hours, None if pd.isna(r.covered_hours) else r.covered_hours)
                for r in df.itertuples()]
        cur.executemany(f"INSERT INTO fdd.rule_result VALUES ({', '.join([ph] * 9)})", rows)
        cur.executemany(f"INSERT INTO fdd.point VALUES ({ph}, {ph}, {ph}, {ph}, {ph})",
                        [("S", f"P{u}", f"U{u}", "supply_air_temp", "numeric") for u in range(1, 5)])
        ts = pd.date_range("2026-02-01", periods=10 * 96, freq="15min", tz="UTC")
        rng = np.random.default_rng(5)
        samples = [("S", f"P{u}", conv(t), float(13 + rng.normal(0, 0.3))) for u in range(1, 5) for t in ts]
        cur.executemany(f"INSERT INTO fdd.input_sample VALUES ({ph}, {ph}, {ph}, {ph})", samples)
        conn.commit()
        got = screen_sql(conn, SourceMap(site_id="S"), HistoryMap())
    finally:
        if engine == "postgres" and created_pg_schema:
            conn.rollback()
            conn.cursor().execute("DROP SCHEMA fdd CASCADE")
            conn.commit()
        conn.close()
    ref = screen(results=df)
    assert len(got["episodes"]) == len(ref["episodes"]) == 5
    assert got["episodes"]["history_assessed"].all()
    assert int(got["rules"].iloc[0]["n_unassessed"]) == 1


def test_identifiers_are_validated():
    assert ident("fdd.rule_result") == "fdd.rule_result"
    for bad in ("x; DROP TABLE y", "a b", "1abc", "t.c.d"):
        with pytest.raises(ValueError):
            ident(bad)


# --------------------------------------------------------------------------- report and scale


def test_report_json_and_markdown():
    fl, hs = _fixture()
    res = screen(fl, hs)
    rep = build_report(res, top=5)
    assert rep["totals"]["episodes"] == len(res["episodes"])
    assert rep["likely_real"] and rep["likely_real"][0]["equipment_id"] == "EQ-1"
    assert any(r["rule_id"] == "R-TIGHT" for r in rep["rules_to_review"])
    assert rep["false_positive_patterns"]
    assert rep["next_checks"]
    json.dumps(rep, default=str)
    md = to_markdown(rep)
    assert md.startswith("# Fault triage") and "## Check next" in md


def test_scale_many_rows_in_sql(tmp_path):
    """100 units x 4 rules x 30 days at 15 min = 1.15 M flag rows aggregated in SQLite without pandas holding them."""
    n_units, n_rules, days = 100, 4, 30
    if os.environ.get("OPENFDD_SCALE_SMALL"):
        n_units = 20
    periods = days * 96
    conn = sqlite3.connect(tmp_path / "big.db")
    conn.execute("CREATE TABLE f (timestamp TEXT, equipment_id TEXT, rule_id TEXT, flag INTEGER)")
    ts = pd.date_range("2026-01-01", periods=periods, freq="15min", tz="UTC").strftime("%Y-%m-%dT%H:%M:%S.%fZ").tolist()
    rng = np.random.default_rng(3)
    for u in range(n_units):
        for r in range(n_rules):
            flag = np.zeros(periods, dtype=int)
            for s in rng.integers(0, periods - 50, 5):
                flag[s:s + rng.integers(4, 40)] = 1
            conn.executemany("INSERT INTO f VALUES (?, ?, ?, ?)",
                             zip(ts, [f"U{u}"] * periods, [f"R{r}"] * periods, flag.tolist()))
    conn.commit()
    src = SourceMap.for_flags("f", columns={"site_id": "", "value": "", "threshold": "", "running": ""})
    res = screen_sql(conn, src, None, ConfidenceConfig(gap_samples=0))
    n_rows = conn.execute("SELECT COUNT(*) FROM f").fetchone()[0]
    expected = conn.execute(
        "WITH s AS (SELECT flag, LAG(flag) OVER (PARTITION BY equipment_id, rule_id ORDER BY timestamp) AS prev FROM f) "
        "SELECT COUNT(*) FROM s WHERE flag = 1 AND (prev IS NULL OR prev = 0)").fetchone()[0]
    conn.close()
    assert n_rows == n_units * n_rules * periods
    assert len(res["episodes"]) == expected
    assert len(res["equipment"]) == n_units


def test_cli_reads_sqlite_and_duckdb_files(tmp_path):
    df = _results_rows()
    for c in ("window_start", "window_end"):
        df[c] = df[c].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    db = tmp_path / "fdd.db"
    with sqlite3.connect(db) as conn:
        df.to_sql("rule_result", conn, index=False)
    out = tmp_path / "o1"
    assert main(["--sqlite", str(db), "--no-history", "--out-dir", str(out), "--print", "none"]) == 0
    rep = json.loads((out / "report.json").read_text())
    assert rep["totals"]["episodes"] == 5
    assert rep["source"]["input"] == "sqlite"
    duckdb = pytest.importorskip("duckdb")
    ddb = tmp_path / "fdd.duckdb"
    with duckdb.connect(str(ddb)) as conn:
        conn.execute("CREATE TABLE results_v2 AS SELECT equipment_id AS equip, rule_id, window_start, window_end, "
                     "CASE status WHEN 'FAULT' THEN 'ALARM' WHEN 'PASS' THEN 'OK' ELSE status END AS state "
                     "FROM df")
    out2 = tmp_path / "o2"
    assert main(["--duckdb", str(ddb), "--table", "results_v2", "--map", "equipment_id=equip", "--map", "status=state",
                 "--map", "site_id=", "--map", "subject_key=", "--map", "fault_hours=", "--map", "covered_hours=",
                 "--fault-status", "ALARM", "--pass-status", "OK", "--no-history", "--out-dir", str(out2),
                 "--print", "none"]) == 0
    assert json.loads((out2 / "report.json").read_text())["totals"]["episodes"] == 5


# --------------------------------------------------------------------------- calibration against reviewed episodes


def _labeled_fleet(units: int = 30, seed: int = 4) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-03-01", periods=3 * 96, freq="15min", tz="UTC")
    flags, hist, labels = [], [], []
    for u in range(units):
        eq = f"U{u:02d}"
        kind = ("real", "fp", "none")[u % 3]
        sat = 13.0 + rng.normal(0, 0.4, ts.size)
        run = np.ones(ts.size, dtype=int)
        a = int(rng.integers(20, 200))
        b = a + int(rng.integers(8, 40))
        if kind == "real":
            sat[a:b] += rng.uniform(3, 7)
        elif kind == "fp":
            sat[a:b] = sat[a - 1] + rng.uniform(2.0, 3.0)
            run[a:b] = 0
        tight = 13.2 + rng.uniform(-0.1, 0.1)
        for i, t in enumerate(ts):
            hist.append((t, eq, "sat", sat[i]))
            flags.append((t, eq, "R-SAT", int(sat[i] > 15.0), sat[i], 15.0, run[i]))
            flags.append((t, eq, "R-TIGHT", int(sat[i] > tight), sat[i], tight, run[i]))
        if kind != "none":
            labels.append((eq, ts[a], ts[b - 1], "fault" if kind == "real" else "normal", "R-SAT"))
        labels.append((eq, ts[0], ts[-1], "normal", "R-TIGHT"))
    fl = pd.DataFrame(flags, columns=["timestamp", "equipment_id", "rule_id", "flag", "value", "threshold", "running"])
    hs = pd.DataFrame(hist, columns=["timestamp", "equipment_id", "point_id", "value"])
    lb = pd.DataFrame(labels, columns=["equipment_id", "start_ts", "end_ts", "label", "rule_id"])
    return fl, hs, lb


def test_calibration_fits_and_reports_held_out_metrics():
    from open_fdd.ml.confidence_calibrate import calibrate

    fl, hs, lb = _labeled_fleet()
    scored = screen(fl, hs)["episodes"]
    out, info = calibrate(scored, lb)
    assert info["status"] == "fitted", info
    assert info["fault"] >= 5 and info["normal"] >= 5
    ho = info["held_out"]
    assert ho["calibrated"]["auc"] >= 0.8
    assert ho["calibrated"]["brier"] <= ho["heuristic"]["brier"] + 0.02
    assert out["p_real_calibrated"].between(0, 1).all()


def test_calibration_needs_enough_labels():
    from open_fdd.ml.confidence_calibrate import calibrate

    fl, hs, lb = _labeled_fleet(units=6)
    out, info = calibrate(screen(fl, hs)["episodes"], lb.head(3))
    assert info["status"].startswith("not fitted")
    assert out["p_real_calibrated"].isna().all()


def test_rule_specific_label_beats_rule_agnostic():
    from open_fdd.ml.confidence_calibrate import label_episodes

    ep = pd.DataFrame({"equipment_id": ["E1"], "rule_id": ["FC1"], "start": [pd.Timestamp("2026-01-01T00:00Z")],
                       "end": [pd.Timestamp("2026-01-01T01:00Z")]})
    lb = pd.DataFrame({"equipment_id": ["E1", "E1"], "start_ts": ["2026-01-01T00:00Z"] * 2, "end_ts": ["2026-01-01T01:00Z"] * 2,
                       "label": ["fault", "normal"], "rule_id": [None, "FC1"]})
    assert label_episodes(ep, lb).tolist() == [0.0]


def test_cli_with_labels_adds_calibration(tmp_path):
    fl, hs, lb = _labeled_fleet(units=15)
    fl.to_csv(tmp_path / "f.csv", index=False)
    hs.to_csv(tmp_path / "h.csv", index=False)
    lb.to_csv(tmp_path / "l.csv", index=False)
    assert main(["--flags", str(tmp_path / "f.csv"), "--history", str(tmp_path / "h.csv"), "--labels", str(tmp_path / "l.csv"),
                 "--out-dir", str(tmp_path / "o"), "--print", "none"]) == 0
    rep = json.loads((tmp_path / "o" / "report.json").read_text())
    assert rep["calibration"]["status"] == "fitted"
    assert "Calibration against reviewed episodes" in (tmp_path / "o" / "report.md").read_text()


# --------------------------------------------------------------------------- review regressions


def test_co_rules_sweep_matches_pairwise():
    rng = np.random.default_rng(11)
    t0 = pd.Timestamp("2026-01-01", tz="UTC")
    rows = []
    for i in range(300):
        s = t0 + pd.Timedelta(hours=int(rng.integers(0, 2000)))
        rows.append({"equipment_id": f"U{i % 3}", "rule_id": f"R{rng.integers(0, 6)}", "start": s,
                     "end": s + pd.Timedelta(hours=int(rng.integers(0, 30)))})
    ep = pd.DataFrame(rows)
    want = []
    for i, a in ep.iterrows():
        o = ep[(ep["equipment_id"] == a["equipment_id"]) & (ep["rule_id"] != a["rule_id"])
               & (ep["start"] <= a["end"]) & (ep["end"] >= a["start"])]
        want.append(o["rule_id"].nunique())
    np.testing.assert_array_equal(_co_rules(ep), np.array(want, dtype=float))


def test_empty_fault_status_is_rejected():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(ValueError):
        screen_sql(conn, SourceMap(table="t", fault_status=()))


def test_csv_input_rejects_database_filters(tmp_path):
    _results_rows().to_csv(tmp_path / "r.csv", index=False)
    with pytest.raises(ValueError):
        main(["--results", str(tmp_path / "r.csv"), "--since", "2026-02-05", "--print", "none",
              "--out-dir", str(tmp_path / "o")])


def test_sqlite_path_with_hash_opens_that_file_read_only(tmp_path):
    db = tmp_path / "building#east.db"
    df = _results_rows()
    conn = sqlite3.connect(db)
    df.assign(window_start=df["window_start"].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
              window_end=df["window_end"].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")).to_sql("rr", conn, index=False)
    conn.close()
    assert main(["--sqlite", str(db), "--table", "rr", "--no-history", "--print", "none",
                 "--out-dir", str(tmp_path / "o")]) == 0
    assert json.loads((tmp_path / "o" / "report.json").read_text())["totals"]["episodes"] == 5
    assert not (tmp_path / "building").exists()


def test_since_bound_is_normalised_for_sqlite_text_timestamps(tmp_path):
    df = _results_rows()
    conn = sqlite3.connect(":memory:")
    df.assign(window_start=df["window_start"].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
              window_end=df["window_end"].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")).to_sql("rr", conn, index=False)
    # window_end of day 8 is 2026-02-10T00:00Z; a space-separated, offset bound must compare the same instant
    got = screen_sql(conn, SourceMap(table="rr", since="2026-02-09 18:00:00-06:00"), None)
    assert set(got["episodes"]["start"].dt.day) == {10}


def test_history_is_scoped_to_the_requested_site():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE rr (site_id TEXT, equipment_id TEXT, rule_id TEXT, window_start TEXT, window_end TEXT, "
                "status TEXT)")
    cur.execute("CREATE TABLE p (site_id TEXT, point_key TEXT, equipment_id TEXT, kind TEXT)")
    cur.execute("CREATE TABLE h (site_id TEXT, point_key TEXT, ts TEXT, value REAL)")
    cur.execute("INSERT INTO rr VALUES ('A', 'U1', 'R', '2026-02-01T00:00:00.000000Z', '2026-02-01T06:00:00.000000Z', "
                "'FAULT')")
    for site in ("A", "B"):
        cur.execute("INSERT INTO p VALUES (?, 'P1', 'U1', 'numeric')", (site,))
    ts = pd.date_range("2026-01-31", periods=200, freq="15min", tz="UTC").strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    cur.executemany("INSERT INTO h VALUES ('B', 'P1', ?, 1.0)", [(t,) for t in ts])
    got = screen_sql(conn, SourceMap(table="rr", site_id="A", columns={"subject_key": "", "fault_hours": "",
                                                                       "covered_hours": ""}),
                     HistoryMap(table="h", point_table="p"))
    assert not got["episodes"]["history_assessed"].any()
    # without a site filter the default point join still reads history (three parameters, no site binding)
    cur.executemany("INSERT INTO h VALUES ('A', 'P1', ?, 1.0)", [(t,) for t in ts])
    got = screen_sql(conn, SourceMap(table="rr", columns={"subject_key": "", "fault_hours": "", "covered_hours": ""}),
                     HistoryMap(table="h", point_table="p"))
    assert got["episodes"]["history_assessed"].all()


def test_unresolved_episodes_are_not_reported_all_clear():
    from open_fdd.ml.confidence_report import next_checks

    rep = {"equipment_ranking": [], "likely_real": [], "false_positive_patterns": [], "rules_to_review": [],
           "totals": {"episodes": 2}}
    assert "review" in next_checks(rep)[0]


def test_auc_counts_ties_as_half():
    from open_fdd.ml.confidence_calibrate import _metrics

    y = np.array([1, 1, 0, 0, 1, 0])
    p = np.array([0.9, 0.5, 0.5, 0.1, 0.7, 0.7])
    pos, neg = p[y == 1], p[y == 0]
    want = ((pos[:, None] > neg).sum() + 0.5 * (pos[:, None] == neg).sum()) / (len(pos) * len(neg))
    assert _metrics(y, p)["auc"] == pytest.approx(round(want, 4))


def test_cli_writes_episode_jsonl_without_nan(tmp_path):
    fl, hs = _fixture()
    fl.to_csv(tmp_path / "f.csv", index=False)
    hs.to_csv(tmp_path / "h.csv", index=False)
    assert main(["--flags", str(tmp_path / "f.csv"), "--history", str(tmp_path / "h.csv"), "--print", "none",
                 "--out-dir", str(tmp_path / "o")]) == 0
    lines = (tmp_path / "o" / "episodes.jsonl").read_text().splitlines()
    eps = pd.read_csv(tmp_path / "o" / "episodes.csv")
    assert len(lines) == len(eps) > 0
    recs = [json.loads(x) for x in lines]
    assert {"episode_id", "label", "p_real", "reason", "evidence"} <= set(recs[0])
    assert recs[0]["start"].endswith("Z")
    assert all(abs(r["p_real"] + r["p_false_positive"] + r["p_tuning"] - 1) <= 2e-3 for r in recs)
