"""CLI help for open-fdd-anomaly."""

from __future__ import annotations

from open_fdd.analytics.anomaly.cli import main


def test_root_help_exits_zero_and_mentions_screen(capsys):
    code = main(["--help"])
    captured = capsys.readouterr()
    assert code == 0
    assert "screen" in captured.out


def test_screen_import_error_exits_2(monkeypatch, capsys, tmp_path):
    def boom(*_args, **_kwargs):
        raise ImportError("pip install 'open-fdd[anomaly]'")

    monkeypatch.setattr("open_fdd.analytics.anomaly.screen.screen_folder", boom)
    code = main(["screen", str(tmp_path), "--out", str(tmp_path / "out")])
    assert code == 2
    assert "open-fdd[anomaly]" in capsys.readouterr().err


def test_report_help_mentions_scope(capsys):
    code = main(["report", "--help"])
    text = capsys.readouterr().out
    assert code == 0
    assert "--scope" in text
    assert "single-system" in text
    assert "building" in text
    assert "--month" in text
    assert "--web-oat" in text


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
