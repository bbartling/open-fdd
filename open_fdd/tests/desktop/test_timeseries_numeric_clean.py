"""Unit tests for Grafana-style numeric coercion."""

from __future__ import annotations

import pandas as pd

from open_fdd.desktop.services.timeseries_numeric_clean import (
    coerce_metrics_to_numeric,
    suggest_coercible_columns,
)


def test_suggest_detects_psi_and_deg_f_columns() -> None:
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
            "pressure": ["1.0 psi", "2.5 psi"],
            "temp": ["70 °F", "71 °F"],
            "label": ["a", "b"],
        },
    )
    s = suggest_coercible_columns(df, min_ratio=0.35)
    assert "pressure" in s and "temp" in s
    assert "label" not in s


def test_coerce_produces_floats() -> None:
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
            "pressure": ["1.0 psi", "2.5 psi"],
        },
    )
    out, stats = coerce_metrics_to_numeric(df, columns={"pressure"})
    assert pd.api.types.is_numeric_dtype(out["pressure"])
    assert float(out["pressure"].iloc[0]) == 1.0
    assert stats["pressure"]["kind"] == "string_to_float"
