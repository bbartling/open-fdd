"""Scoreboard and ranking for a mini AHU folder."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from open_fdd.analytics.anomaly.screen import screen_folder

FIXTURE = Path(__file__).parent / "fixtures" / "mini_ahu"
COLUMNS = ["point", "role", "method", "anomaly_minutes", "event_count", "skipped_reason"]


def test_screen_writes_scoreboard_and_ranks_spiked_point(tmp_path):
    out = tmp_path / "out"
    result = screen_folder(
        FIXTURE,
        out,
        top_n=2,
        max_days=3,
        methods=["zscore", "mad"],
        command="open-fdd-anomaly screen mini_ahu --out out --methods zscore,mad",
    )
    board = pd.read_csv(out / "scoreboard.csv")
    assert list(board.columns) == COLUMNS
    assert "RAT_MISSING" not in set(board["point"])

    dat = board[board["point"] == "DAT"]
    assert set(dat["method"]) == {"zscore", "mad"}
    assert float(dat["anomaly_minutes"].sum()) > 0

    fan = board[board["point"] == "SF_S"]
    assert len(fan) == 1
    assert fan.iloc[0]["skipped_reason"] == "binary_like"

    active = board[board["skipped_reason"].fillna("") == ""]
    totals = active.groupby("point")["anomaly_minutes"].sum()
    assert float(totals["DAT"]) > float(totals.get("MAT", 0.0))
    assert result.top_points[0] == "DAT"
    assert "2026-01-02" in {day.isoformat() for day in result.days_by_point["DAT"]}

    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "SQL-portable" in readme
    assert "Python-only" in readme
    assert "UTC" in readme
    assert "zscore,mad" in readme
