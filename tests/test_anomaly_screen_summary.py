"""screen: machine-readable summary, --no-plots and --tz (#1655)."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from open_fdd.analytics.anomaly.screen import check_tz, flagged_windows


def test_flagged_windows_in_a_local_zone():
    idx = pd.date_range("2026-01-06 02:50", periods=8, freq="5min", tz="UTC")
    flags = pd.Series([False, True, True, False, False, True, False, True], index=idx)
    got = flagged_windows(flags, pd.Timedelta(minutes=5), "America/Chicago")
    assert got == [
        {"start": "2026-01-05T20:55:00-06:00", "end": "2026-01-05T21:05:00-06:00", "minutes": 10.0},
        {"start": "2026-01-05T21:15:00-06:00", "end": "2026-01-05T21:20:00-06:00", "minutes": 5.0},
        {"start": "2026-01-05T21:25:00-06:00", "end": "2026-01-05T21:30:00-06:00", "minutes": 5.0},
    ]
    assert flagged_windows(flags & False, pd.Timedelta(minutes=5)) == []
    with pytest.raises(ValueError, match="time zone"):
        check_tz("Mars/Olympus")


def _folder(tmp_path):
    rng = np.random.default_rng(11)
    n = 3 * 288
    idx = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    discharge_air_temperature = 13 + rng.normal(0, 0.3, n)
    spike = int((pd.Timestamp("2026-01-07T03:00Z") - idx[0]) / pd.Timedelta(minutes=5))
    discharge_air_temperature[spike : spike + 3] = 25.0  # 03:00 UTC on Jan 7 is 21:00 on Jan 6 in Chicago
    folder = tmp_path / "AHU_1"
    folder.mkdir()
    pd.DataFrame({"timestamp_utc": idx.strftime("%Y-%m-%dT%H:%M:%SZ"), "SAT": discharge_air_temperature, "FAN": 1.0}).to_csv(
        folder / "history_wide.csv", index=False
    )
    (folder / "column_map.json").write_text(
        json.dumps({"equipType": "AHU", "points": {"discharge_air_temperature": "SAT", "supply_fan_operating_status": "FAN"}}), encoding="utf-8"
    )
    return folder


def _zscore_row(summary):
    return next(r for r in summary["points"] if r["point"] == "SAT" and r["method"] == "zscore")


def test_json_stdout_no_plots_and_local_days(tmp_path, capsys):
    pytest.importorskip("matplotlib")
    from open_fdd.analytics.anomaly.cli import main

    folder = _folder(tmp_path)
    out = tmp_path / "chi"
    rc = main(["screen", str(folder), "--out", str(out), "--methods", "zscore", "--json", "--no-plots",
               "--tz", "America/Chicago", "--top-n", "1", "--max-days", "2"])
    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert printed["tz"] == "America/Chicago" and printed["plots"] is False
    assert not list(out.rglob("*.png"))
    row = _zscore_row(printed)
    spike = {"start": "2026-01-06T21:00:00-06:00", "end": "2026-01-06T21:15:00-06:00", "minutes": 15.0}
    assert spike in row["windows"] and row["windows_total"] == len(row["windows"])
    assert sum(w["minutes"] for w in row["windows"]) == row["anomaly_minutes"]
    assert row["minutes_by_day"]["2026-01-06"] >= 15.0
    assert "2026-01-06" in printed["days_by_point"]["SAT"]
    assert printed["flagged_points"] == ["SAT"] and printed["activity"]["proof_source"] == "supply_fan_operating_status"
    assert "**America/Chicago**" in (out / "README.md").read_text(encoding="utf-8")

    utc = tmp_path / "utc"
    assert main(["screen", str(folder), "--out", str(utc), "--methods", "zscore", "--json", str(tmp_path / "s.json"),
                 "--top-n", "1", "--max-days", "2"]) == 0
    written = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert written["tz"] == "UTC"
    utc_row = _zscore_row(written)
    assert {"start": "2026-01-07T03:00:00+00:00", "end": "2026-01-07T03:15:00+00:00", "minutes": 15.0} in utc_row["windows"]
    assert utc_row["minutes_by_day"]["2026-01-07"] >= 15.0
    assert (utc / "scoreboard_bar.png").exists()
    assert list((utc / "days").rglob("*.png"))


def test_bad_tz_exits_2(tmp_path, capsys):
    from open_fdd.analytics.anomaly.cli import main

    assert main(["screen", str(_folder(tmp_path)), "--out", str(tmp_path / "x"), "--tz", "Nowhere/Zone"]) == 2
    assert "time zone" in capsys.readouterr().err


def test_local_day_slice_handles_dst():
    from open_fdd.analytics.anomaly.plots import _day_slice

    idx = pd.date_range("2026-03-07", periods=3 * 288, freq="5min", tz="UTC")
    s = pd.Series(1.0, index=idx)
    assert len(_day_slice(s, date(2026, 3, 8), "America/Chicago")) == 23 * 12
    assert len(_day_slice(s, date(2026, 3, 8))) == 24 * 12
