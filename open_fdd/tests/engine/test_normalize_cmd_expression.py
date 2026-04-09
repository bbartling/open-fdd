"""normalize_cmd in expression namespace."""

import pandas as pd

from open_fdd.engine.checks import check_expression


def test_normalize_cmd_percent_in_expression():
    df = pd.DataFrame(
        {
            "vfd": [0.95, 95.0, 50.0],
        }
    )
    col_map = {"Supply_Fan_Speed_Command": "vfd"}
    # Mixed column: any >1 triggers /100 for whole series (documented heuristic)
    expr = "normalize_cmd(Supply_Fan_Speed_Command) >= 0.9"
    mask = check_expression(df, expr, col_map, {})
    assert mask.dtype == bool
    assert mask.any()


def test_normalize_cmd_fraction_only_no_scale():
    df = pd.DataFrame({"vfd": [0.5, 0.9, 0.95]})
    col_map = {"Supply_Fan_Speed_Command": "vfd"}
    expr = "normalize_cmd(Supply_Fan_Speed_Command) > 0.85"
    mask = check_expression(df, expr, col_map, {})
    assert mask.sum() == 2
