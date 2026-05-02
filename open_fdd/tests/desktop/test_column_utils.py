from __future__ import annotations

import pandas as pd

from open_fdd.desktop.column_utils import dedupe_dataframe_columns


def test_dedupe_dataframe_columns_renames_repeats() -> None:
    raw = pd.DataFrame([[1, 2, 3]], columns=["a", "a", "b"])
    out = dedupe_dataframe_columns(raw)
    assert list(out.columns) == ["a", "a__1", "b"]
    assert out.columns.is_unique


def test_dedupe_dataframe_columns_noop_when_unique() -> None:
    raw = pd.DataFrame({"x": [1]})
    out = dedupe_dataframe_columns(raw)
    assert list(out.columns) == ["x"]
