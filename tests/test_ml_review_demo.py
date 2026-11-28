"""End-to-end synthetic review demo (#1667 acceptance 6): open_fdd.ml.review_demo."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("pandas")
pytest.importorskip("sklearn")

from open_fdd.ml.review_demo import main  # noqa: E402


def test_demo_runs_end_to_end_and_keeps_the_fault(tmp_path, capsys):
    out = tmp_path / "demo"
    assert main([str(out)]) == 0
    for rel in ("AHU-DEMO/history_wide.csv", "AHU-DEMO/column_map.json", "episodes/stuck.json",
                "reviews/stuck.json", "reviews/healthy_day.json", "labeled.json", "eval.json"):
        assert (out / rel).is_file(), rel
    stuck = json.loads((out / "reviews" / "stuck.json").read_text(encoding="utf-8"))
    assert stuck["outcome"] == "corroborated" and stuck["sql_verdict_kept"]
    ev = json.loads((out / "eval.json").read_text(encoding="utf-8"))
    raw = ev["overall"]["tiers"]["raw_sql"]
    assert raw["alerts"] == 2 and raw["missed"] == []
    assert ev["claim_supported"] is False  # two episodes cannot support a claim
    assert '"claim_supported": false' in capsys.readouterr().out  # the printed summary


def test_demo_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert main([str(a)]) == 0 and main([str(b)]) == 0
    assert (a / "AHU-DEMO" / "history_wide.csv").read_bytes() == (b / "AHU-DEMO" / "history_wide.csv").read_bytes()
    ra = json.loads((a / "reviews" / "stuck.json").read_text(encoding="utf-8"))
    rb = json.loads((b / "reviews" / "stuck.json").read_text(encoding="utf-8"))
    assert ra["outcome"] == rb["outcome"] and ra["methods"] == rb["methods"]


def test_demo_gates_the_off_hours_and_refuses_a_non_empty_out(tmp_path, capsys):
    out = tmp_path / "demo"
    assert main([str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    # the fan is off 00:00-05:00 UTC daily: each one-day episode has 288 rows, 228 proven running
    assert printed["active_rows"] == {"stuck": 228, "healthy_day": 228}
    stuck = json.loads((out / "reviews" / "stuck.json").read_text(encoding="utf-8"))
    assert stuck["window"]["proof_source"] == "supply_fan_operating_status" and stuck["training"]["proven_rows"] < stuck["window"]["rows"] * 6
    assert len(printed) and "reviews" not in printed  # a short summary, not the full review JSON
    ev = json.loads((out / "eval.json").read_text(encoding="utf-8"))
    assert ev["exposure"]["test_device_weeks"] == round(4 / 7, 4)
    assert main([str(out)]) == 2 and "not empty" in capsys.readouterr().err
    assert main([str(out), "--force"]) == 0
