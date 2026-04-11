"""FDD loop integration with open-fdd RuleRunner.run keyword compatibility."""

from openfdd_stack.platform.loop import _fdd_runner_run_kwargs


class _Settings:
    rolling_window = None


def test_fdd_runner_run_kwargs_lenient_default():
    m = {"Brick": "col1"}
    kw = _fdd_runner_run_kwargs(_Settings(), strict=False, column_map=m)
    assert kw["column_map"] == m
    assert kw["skip_missing_columns"] is True
    assert kw["params"] == {"units": "imperial"}


def test_fdd_runner_run_kwargs_strict_disables_skip_missing():
    m = {"Brick": "col1"}
    kw = _fdd_runner_run_kwargs(_Settings(), strict=True, column_map=m)
    assert kw["skip_missing_columns"] is False
    # open-fdd 2.3+ adds input_validation; older wheels omit it
    if "input_validation" in kw:
        assert kw["input_validation"] == "strict"
