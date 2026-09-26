"""CLI help for open-fdd-anomaly."""

from __future__ import annotations

from open_fdd.analytics.anomaly.cli import main


def test_root_help_exits_zero_and_mentions_screen(capsys):
    code = main(["--help"])
    captured = capsys.readouterr()
    assert code == 0
    assert "screen" in captured.out


def test_screen_help_exits_zero(capsys):
    code = main(["screen", "--help"])
    captured = capsys.readouterr()
    assert code == 0
    text = captured.out
    assert "screen" in text
    assert "--out" in text
    assert "--top-n" in text
    assert "--max-days" in text
    assert "--methods" in text
