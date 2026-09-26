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
    assert "--week" in text
    assert "--compile" in text
    assert "--profile" in text
    assert "vav_ahu" in text
    assert "cv_ahu" in text
    assert "report.pdf" in text
    assert "2026-04-06" in text
    assert "--title" in text
    assert "--location" in text
    assert "Open-FDD AI Agent Report" in text
    assert "Detroit" in text


def test_report_passes_week_and_month(monkeypatch, tmp_path):
    seen: dict = {}

    def fake(folder, out, **kwargs):
        seen["folder"] = folder
        seen["out"] = out
        seen.update(kwargs)

    monkeypatch.setattr(
        "open_fdd.reporting.single_system_typst.build_single_system_report",
        fake,
    )
    code = main(
        [
            "report",
            str(tmp_path),
            "--out",
            str(tmp_path / "out"),
            "--month",
            "2026-04",
            "--week",
            "2026-04-06",
            "--web-oat",
            "open_meteo_april.csv",
        ]
    )
    assert code == 0
    assert seen["month"] == "2026-04"
    assert seen["week"] == "2026-04-06"
    assert seen["web_oat"] == "open_meteo_april.csv"
    assert seen["title"] is None
    assert seen["location"] is None


def test_report_passes_title_and_location(monkeypatch, tmp_path):
    seen: dict = {}

    def fake(folder, out, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(
        "open_fdd.reporting.single_system_typst.build_single_system_report",
        fake,
    )
    code = main(
        [
            "report",
            str(tmp_path),
            "--out",
            str(tmp_path / "out"),
            "--title",
            "Site report",
            "--location",
            "AHU · ACME Office · Detroit, MI",
        ]
    )
    assert code == 0
    assert seen["title"] == "Site report"
    assert seen["location"] == "AHU · ACME Office · Detroit, MI"


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
