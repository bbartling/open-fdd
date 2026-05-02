from __future__ import annotations

import pandas as pd

from open_fdd.desktop.services.plot_readiness import analyze_dataframe_for_plot


def test_plot_readiness_all_numeric() -> None:
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=5, freq="h"),
            "oat": [40.0, 41.0, 42.0, 43.0, 44.0],
        }
    )
    r = analyze_dataframe_for_plot(df)
    assert r.ok is True
    assert r.recommend_clean_metrics is False
    assert r.metric_columns_not_plot_ready == 0


def test_plot_readiness_suggests_clean_for_unit_strings() -> None:
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=5, freq="h"),
            "temp": ["40.0 °F", "41.0 °F", "42.0 °F", "43.0 °F", "44.0 °F"],
        }
    )
    r = analyze_dataframe_for_plot(df)
    assert r.ok is False
    assert r.recommend_clean_metrics is True
    temp = next(c for c in r.columns if c.name == "temp")
    assert temp.plot_line_ready is False
    assert temp.recommend_clean_metrics is True
