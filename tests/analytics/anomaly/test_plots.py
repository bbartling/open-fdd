"""Smoke tests: anomaly plots exist and are non-empty PNGs."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from open_fdd.analytics.anomaly.plots import (
    write_day_zoom,
    write_scoreboard_bar,
    write_support_plots,
)
from open_fdd.analytics.anomaly.screen import screen_folder

FIXTURE = Path(__file__).parent / "fixtures" / "mini_ahu"


def _assert_png(path: Path) -> None:
    assert path.is_file(), path
    assert path.stat().st_size > 100


def test_plot_helpers_write_nonempty_pngs(tmp_path):
    idx = pd.date_range("2026-01-02", periods=24, freq="h", tz="UTC")
    series = pd.Series(np.linspace(50.0, 60.0, 24), index=idx)
    series.iloc[10] = 90.0
    flags = {
        "zscore": pd.Series(False, index=idx),
        "mad": pd.Series(False, index=idx),
    }
    flags["zscore"].iloc[10] = True
    flags["mad"].iloc[10] = True
    board = pd.DataFrame(
        {
            "point": ["DAT", "DAT"],
            "role": ["discharge-air-temp", "discharge-air-temp"],
            "method": ["zscore", "mad"],
            "anomaly_minutes": [60.0, 30.0],
            "event_count": [1, 1],
            "skipped_reason": ["", ""],
        }
    )
    write_scoreboard_bar(board, tmp_path / "scoreboard_bar.png")
    write_support_plots("DAT", series, flags, tmp_path)
    write_day_zoom(
        "DAT",
        series,
        flags,
        date(2026, 1, 2),
        tmp_path / "days" / "DAT" / "2026-01-02.png",
    )
    for rel in (
        "scoreboard_bar.png",
        "overview/DAT_line.png",
        "dist/DAT_hist.png",
        "dist/DAT_box.png",
        "days/DAT/2026-01-02.png",
    ):
        _assert_png(tmp_path / rel)


def test_screen_folder_writes_support_plots_and_top_day_zooms(tmp_path):
    out = tmp_path / "out"
    result = screen_folder(FIXTURE, out, top_n=1, max_days=2, methods=["zscore", "mad"])
    _assert_png(out / "scoreboard_bar.png")
    _assert_png(out / "overview" / "DAT_line.png")
    _assert_png(out / "dist" / "DAT_hist.png")
    _assert_png(out / "dist" / "DAT_box.png")
    _assert_png(out / "overview" / "MAT_line.png")
    assert not (out / "overview" / "SF_S_line.png").exists()
    assert result.top_points == ["DAT"]
    assert result.days_by_point["DAT"]
    for day in result.days_by_point["DAT"]:
        _assert_png(out / "days" / "DAT" / f"{day.isoformat()}.png")
    assert list((out / "days").glob("MAT/*.png")) == []
