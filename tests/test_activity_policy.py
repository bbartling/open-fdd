"""Shared activity policy for screen and ml detect (#1656)."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from open_fdd.analytics.anomaly.activity import activity, activity_mask, is_site_role

NAN = math.nan


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")


def test_status_on_off_null_are_separate_states():
    frame = pd.DataFrame({"fan-status": [1.0, 0.0, NAN, 1.0]}, index=_idx(4))
    act = activity(frame)
    assert act.state.tolist() == ["on", "off", "unknown", "on"]
    r = act.receipt()
    assert (r["proof_source"], r["proof_kind"], r["threshold"]) == ("fan-status", "status", 0.05)
    assert (r["on_rows"], r["off_rows"], r["unknown_rows"], r["assessed_rows"]) == (2, 1, 1, 2)
    assert r["assessed_fraction"] == 0.5


def test_absent_proof_is_unknown_and_unassessed_unless_ungated():
    frame = pd.DataFrame({"discharge-air-temp": [13.0, 14.0, 15.0]}, index=_idx(3))
    act = activity(frame)
    assert act.source == "none"
    assert act.state.eq("unknown").all()
    assert not activity_mask(frame).any()
    loose = activity(frame, policy="ungated")
    assert loose.assessed.all()
    assert loose.receipt()["unknown_rows"] == 3  # the proof counts are still disclosed
    with pytest.raises(ValueError, match="activity policy"):
        activity(frame, policy="sometimes")


def test_status_wins_over_command_with_no_row_level_fallback():
    frame = pd.DataFrame({"fan-status": [0.0, NAN, 1.0], "fan-cmd": [1.0, 1.0, 0.0]}, index=_idx(3))
    act = activity(frame)
    assert act.source == "fan-status"
    assert act.state.tolist() == ["off", "unknown", "on"]
    # A status column with no data at all is absent, so the command is the declared source.
    frame["fan-status"] = NAN
    act = activity(frame)
    assert (act.source, act.source_kind) == ("fan-cmd", "command")
    assert act.state.tolist() == ["on", "on", "off"]


def test_short_alias_names_and_occupancy():
    frame = pd.DataFrame(
        {"fan_status": [1.0, 1.0, 1.0, 0.0], "occ_mode": [1.0, 0.0, NAN, 1.0]}, index=_idx(4)
    )
    act = activity(frame)
    assert act.source == "fan-status"
    assert act.occupancy_source == "occupied"
    assert act.state.tolist() == ["on", "unoccupied", "unknown", "off"]


def test_resolved_run_proof_and_other_equipment_status():
    # canonical precedence (run_proof.json / derive_run_proof): the resolved run-proof column beats an own status
    pump = pd.DataFrame({"pump-status": [1.0, 0.0], "run-proof": [0.0, 1.0]}, index=_idx(2))
    act = activity(pump)
    assert (act.source, act.source_kind, act.state.tolist()) == ("run-proof", "run_proof", ["off", "on"])
    only_pump = pump.drop(columns=["run-proof"])
    assert (activity(only_pump).source, activity(only_pump).state.tolist()) == ("pump-status", ["on", "off"])
    resolved = pd.DataFrame({"run-proof": [1.0, 0.0, NAN], "chw-pump-cmd": [0.0, 1.0, 1.0]}, index=_idx(3))
    act = activity(resolved)
    assert (act.source, act.source_kind) == ("run-proof", "run_proof")
    assert act.state.tolist() == ["on", "off", "unknown"]


def test_fractional_status_uses_the_contract_threshold():
    """A status of 0.3 is running under the contract (> 0.05), the same as the rules' run-proof gate."""
    from open_fdd.run_proof import derive_run_proof, proof_on

    frame = pd.DataFrame({"fan-status": [0.3, 0.04, 0.06, NAN]}, index=_idx(4))
    act = activity(frame)
    assert act.threshold == 0.05
    assert act.state.tolist() == ["on", "off", "on", "unknown"]
    series, column = derive_run_proof(frame)
    assert column == "fan-status"
    assert proof_on(series).tolist()[:3] == [True, False, True]


def test_run_proof_resolved_frame_without_proof_stays_no_proof():
    """A frame the binding layer resolved as "no proof bound" does not fall back to its status or command columns."""
    frame = pd.DataFrame({"fan-status": [1.0, 1.0], "fan-cmd": [1.0, 1.0]}, index=_idx(2))
    frame.attrs["run_proof_resolved"] = True
    act = activity(frame)
    assert act.source == "none" and act.state.eq("unknown").all() and act.skip_reason() == "no_run_proof"
    frame["run-proof"] = [0.0, 1.0]
    act = activity(frame)
    assert (act.source, act.state.tolist()) == ("run-proof", ["off", "on"])


def test_skip_reasons_and_empty_receipt():
    absent = activity(pd.DataFrame({"discharge-air-temp": [13.0]}, index=_idx(1)))
    assert absent.skip_reason() == "no_run_proof"
    idle = activity(pd.DataFrame({"fan-status": [0.0, 0.0]}, index=_idx(2)))
    assert idle.skip_reason() == "no_active_rows"
    occ_unknown = activity(pd.DataFrame({"fan-status": [1.0, 1.0], "occupied": [NAN, 1.0]}, index=_idx(2)))
    assert occ_unknown.state.tolist() == ["unknown", "on"]
    # every row unknown (status missing, or running with occupancy missing): reported apart from "never on"
    all_unknown = activity(pd.DataFrame({"fan-status": [1.0, NAN], "occupied": [NAN, 1.0]}, index=_idx(2)))
    assert all_unknown.state.tolist() == ["unknown", "unknown"]
    assert all_unknown.skip_reason() == "no_known_proof"
    unknown = activity(pd.DataFrame({"fan-status": [1.0, 1.0], "occupied": [NAN, 0.0]}, index=_idx(2)))
    assert unknown.state.tolist() == ["unknown", "unoccupied"]
    empty = activity(pd.DataFrame({"fan-status": pd.Series([], dtype=float)}, index=_idx(0)))
    assert empty.receipt()["assessed_fraction"] is None


def test_site_roles():
    assert is_site_role("outside_air_temp") and is_site_role("outside_air_humidity")
    assert is_site_role("outside-air-temp") and is_site_role("oa_t") and is_site_role("outside-air-humidity")
    assert not is_site_role("outside-air-damper") and not is_site_role("oa_damper_pct")
    assert not is_site_role("discharge-air-temp")


def test_ml_active_mask_uses_the_shared_policy():
    from open_fdd.ml.detectors import active_mask

    frame = pd.DataFrame({"fan_status": [1.0, 0.0, NAN], "sat": [13.0, 13.0, 13.0]}, index=_idx(3))
    assert active_mask(frame).tolist() == [True, False, False]
    assert not active_mask(frame.drop(columns=["fan_status"])).any()


def _folder(tmp_path, name, fan, *, with_fan=True, n=4 * 288):
    rng = np.random.default_rng(3)
    idx = _idx(n)
    hist = pd.DataFrame(
        {
            "timestamp_utc": idx.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "SAT": 13 + rng.normal(0, 0.3, n),
            "MAT": 18 + rng.normal(0, 0.5, n),
            "OAT": 5 + rng.normal(0, 0.5, n),
        }
    )
    for spike in (500, 700, 900):
        hist.loc[spike, ["SAT", "OAT"]] = [30.0, 30.0]
    points = {"sat": "SAT", "mat": "MAT", "oa_t": "OAT"}
    if with_fan:
        hist["FAN"] = fan(n)
        points["fan_status"] = "FAN"
    folder = tmp_path / name
    folder.mkdir()
    hist.to_csv(folder / "history_wide.csv", index=False)
    (folder / "column_map.json").write_text(json.dumps({"equipType": "AHU", "points": points}), encoding="utf-8")
    return folder


def _rows(scoreboard, point):
    return scoreboard[scoreboard["point"] == point]


def test_screen_skips_an_idle_unit_and_agrees_with_ml_detect(tmp_path):
    pytest.importorskip("matplotlib")
    from open_fdd.analytics.anomaly.screen import screen_folder
    from open_fdd.ml.cli import role_frame_from_folder
    from open_fdd.ml.detectors import active_mask

    idle = _folder(tmp_path, "IDLE", lambda n: np.zeros(n))
    res = screen_folder(idle, tmp_path / "s", methods=["zscore"], top_n=0, max_days=0)
    sb = res.scoreboard
    for point in ("SAT", "MAT"):
        row = _rows(sb, point).iloc[0]
        assert (row["skipped_reason"], row["gate"], row["assessed_rows"]) == ("no_active_rows", "proof", 0)
    oat = _rows(sb, "OAT").iloc[0]
    assert (oat["skipped_reason"], oat["gate"]) == ("", "site")
    assert oat["assessed_rows"] == 4 * 288 and oat["anomaly_minutes"] > 0
    assert res.activity["off_rows"] == 4 * 288 and res.activity["assessed_rows"] == 0
    assert int(active_mask(role_frame_from_folder(idle)).sum()) == res.activity["assessed_rows"]
    saved = json.loads((tmp_path / "s" / "activity.json").read_text(encoding="utf-8"))
    assert saved["proof_source"] == "fan-status"
    readme = (tmp_path / "s" / "README.md").read_text(encoding="utf-8")
    assert "## Activity" in readme and "Policy: **proof**" in readme

    loose = screen_folder(idle, tmp_path / "u", methods=["zscore"], top_n=0, max_days=0, activity_policy="ungated")
    sat = _rows(loose.scoreboard, "SAT").iloc[0]
    assert (sat["skipped_reason"], sat["gate"]) == ("", "ungated") and sat["anomaly_minutes"] > 0
    assert "Policy: **ungated**" in (tmp_path / "u" / "README.md").read_text(encoding="utf-8")


def test_screen_without_proof_reports_unassessed(tmp_path):
    pytest.importorskip("matplotlib")
    from open_fdd.analytics.anomaly.screen import screen_folder

    bare = _folder(tmp_path, "BARE", None, with_fan=False)
    res = screen_folder(bare, tmp_path / "s", methods=["zscore"], top_n=0, max_days=0)
    assert _rows(res.scoreboard, "SAT").iloc[0]["skipped_reason"] == "no_run_proof"
    assert res.activity["proof_source"] == "none" and res.activity["unknown_rows"] == 4 * 288
    assert _rows(res.scoreboard, "OAT").iloc[0]["skipped_reason"] == ""


def test_screen_gated_runs_on_proven_rows_only_and_sql_matches(tmp_path):
    pytest.importorskip("matplotlib")
    from open_fdd.analytics.anomaly.screen import screen_folder

    # On for the first half of each day; the SAT spike at row 500 falls on an off row.
    half = _folder(tmp_path, "HALF", lambda n: ((np.arange(n) % 288) < 144).astype(float))
    a = screen_folder(half, tmp_path / "p", methods=["zscore"], top_n=0, max_days=0)
    b = screen_folder(half, tmp_path / "q", methods=["zscore"], top_n=0, max_days=0, engine="sql")
    pd.testing.assert_frame_equal(a.scoreboard, b.scoreboard)
    sat = _rows(a.scoreboard, "SAT").iloc[0]
    assert sat["assessed_rows"] == 2 * 288
    assert a.activity["on_rows"] == 2 * 288 and a.activity["off_rows"] == 2 * 288
    loose = screen_folder(half, tmp_path / "r", methods=["zscore"], top_n=0, max_days=0, activity_policy="ungated")
    assert _rows(loose.scoreboard, "SAT").iloc[0]["assessed_rows"] == 4 * 288


def test_ml_detect_summary_reports_activity(tmp_path, capsys):
    from open_fdd.ml.cli import main

    idle = _folder(tmp_path, "IDLE", lambda n: np.zeros(n))
    assert main(["detect", str(idle), "--method", "zscore", "--out", str(tmp_path / "d")]) == 0
    summary = json.loads((tmp_path / "d" / "summary.json").read_text(encoding="utf-8"))
    assert summary["active_rows"] == 0 and summary["flagged_rows"] == 0
    assert summary["activity"]["proof_source"] == "fan-status"
    assert summary["activity"]["off_rows"] == 4 * 288


def test_screen_survives_duplicate_timestamps(tmp_path):
    """A device folder with repeated timestamps is screened (flags are placed positionally, not by reindex)."""
    pytest.importorskip("matplotlib")
    from open_fdd.analytics.anomaly.screen import screen_folder

    folder = _folder(tmp_path, "AHU_DUP", lambda n: np.where(np.arange(n) % 288 < 144, 1.0, 0.0))
    hist = pd.read_csv(folder / "history_wide.csv")
    hist = pd.concat([hist, hist.iloc[100:110]]).sort_values("timestamp_utc", kind="stable")
    hist.to_csv(folder / "history_wide.csv", index=False)
    res = screen_folder(folder, tmp_path / "s", methods=["zscore", "mad"], top_n=0, max_days=0)
    row = _rows(res.scoreboard, "SAT")
    assert not row.empty and (row["gate"] == "proof").all()
