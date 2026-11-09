"""The SV elapsed-time knobs have a 15-minute minimum and render in seconds."""

from sql.fdd.render_rule import render


def test_sv_window_and_silence_minimum_render_as_elapsed_seconds():
    stale = render("SV-STALE", poll_seconds=420, overrides={"stale_hours": 0.25, "max_silence_hours": 0.25})
    flatline = render("SV-FLATLINE", poll_seconds=420, overrides={"flatline_hours": 0.25, "max_silence_hours": 0.25})
    for sql in (stale, flatline):
        assert "RANGE BETWEEN 900 PRECEDING AND CURRENT ROW" in sql
        assert "900" in sql
        assert "ROWS BETWEEN" not in sql


def test_all_four_sv_rules_allow_quarter_hour_silence():
    for rule_id in ("SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE"):
        sql = render(rule_id, poll_seconds=420, overrides={"max_silence_hours": 0.25})
        assert "epoch_seconds - previous_epoch <= 900" in sql or rule_id != "SV-SPIKE"
        assert "dt_seconds > 900" in sql
