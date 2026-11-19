"""The SV elapsed-time knobs have a 15-minute minimum and render in seconds."""

import pytest

from sql.fdd.render_rule import render


def test_sv_window_and_silence_minimum_render_as_elapsed_seconds():
    flatline = render("SV-FLATLINE", poll_seconds=420, overrides={"flatline_hours": 0.25, "max_silence_hours": 0.25})
    assert "RANGE BETWEEN 900 PRECEDING AND CURRENT ROW" in flatline
    assert "ROWS BETWEEN" not in flatline
    stale = render("SV-STALE", poll_seconds=420, overrides={"stale_after_hours": 0.25})
    assert "dt_seconds > 900" in stale and "ROWS BETWEEN" not in stale


def test_all_four_sv_rules_allow_quarter_hour_silence():
    for rule_id in ("SV-RANGE", "SV-FLATLINE", "SV-SPIKE"):
        sql = render(rule_id, poll_seconds=420, overrides={"max_silence_hours": 0.25})
        assert "epoch_seconds - previous_epoch <= 900" in sql or rule_id != "SV-SPIKE"
        assert "dt_seconds > 900" in sql
    # #1673: a saved max_silence_hours on SV-STALE is its stale threshold (alias of stale_after_hours)
    assert "dt_seconds > 900" in render("SV-STALE", poll_seconds=420, overrides={"max_silence_hours": 0.25})


def test_sv_stale_legacy_keys():
    """#1673: the new key wins over its alias; the value-span / gate / confirm keys are retired."""
    both = render("SV-STALE", overrides={"stale_after_hours": 1.0, "max_silence_hours": 0.25})
    assert "dt_seconds > 3600" in both and "dt_seconds > 900" not in both
    for key in ("stale_hours", "stale_tol", "confirm_min", "require_run_proof", "require_operational_gate"):
        with pytest.raises(ValueError, match="retired"):
            render("SV-STALE", overrides={key: 1.0})
