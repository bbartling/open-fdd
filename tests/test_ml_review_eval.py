"""Labeled held-out evaluation of the episode review policy (#1667 acceptance 5)."""

from __future__ import annotations

import json

import pytest

from open_fdd.ml import review_eval as rv


def _ep(i, *, label, sql=True, outcome="corroborated", split="test", category="sensor", equip="AHU-2",
        start="2026-07-01T00:00:00Z", onset=None, methods=None):
    ep = {"episode_id": f"e{i}", "equipment": equip, "category": category, "split": split, "label": label,
          "label_source": "synthetic", "sql_verdict": "fault" if sql else None, "start_utc": start,
          "sql_start_utc": start}
    if onset:
        ep["label_onset_utc"] = onset
    if sql:
        ep["review"] = {"outcome": outcome, "methods": methods or {}}
    return ep


def _corpus():
    eps = [
        _ep(1, label="fault", onset="2026-06-30T22:00:00Z", methods={"pca": {"status": "corroborates"}}),
        _ep(2, label="fault", outcome="needs_review", category="coil", methods={"pca": {"status": "quiet"}}),
        _ep(3, label="healthy", outcome="corroborated", methods={"pca": {"status": "corroborates"}}),
        _ep(4, label="healthy", outcome="needs_review", methods={"pca": {"status": "quiet"}}),
        _ep(5, label="unknown", outcome="insufficient_evidence"),
        _ep(6, label="fault", sql=False, category="proof"),  # genuine fault SQL never raised
        _ep(7, label="fault", split="train", equip="AHU-1", start="2026-05-01T00:00:00Z"),
    ]
    return {"device_weeks": {"AHU-2": 4, "AHU-1": 10}, "episodes": eps}


def test_tiers_counts_and_burden():
    res = rv.evaluate(_corpus(), min_labeled=1)
    ov = res["overall"]
    assert ov["episodes"] == 6 and ov["device_weeks"] == 4
    raw, pri = ov["tiers"]["raw_sql"], ov["tiers"]["reviewed_priority"]
    assert raw["alerts"] == 5 and raw["true_alerts"] == 2 and raw["false_alerts"] == 2 and raw["unlabeled_alerts"] == 1
    assert raw["labeled_faults"] == 3 and raw["missed_faults"] == 1 and raw["missed"] == ["e6"]
    assert raw["precision"] == 0.5 and raw["recall"] == round(2 / 3, 4)
    assert raw["alerts_per_device_week"] == 1.25
    assert pri["alerts"] == 2 and pri["recall"] == round(1 / 3, 4) and sorted(pri["missed"]) == ["e2", "e6"]
    assert ov["review_outcomes"] == {"corroborated": 2, "needs_review": 2, "insufficient_evidence": 1,
                                    "not_reviewed": 0}
    assert ov["reviewer_workload"] == 3 and ov["excluded_coverage"] == 0.2
    assert ov["tiers"]["method:pca"]["alerts"] == 2


def test_missed_genuine_faults_visible_per_category():
    res = rv.evaluate(_corpus(), min_labeled=1)
    proof = res["by_category"]["proof"]["tiers"]["raw_sql"]
    coil = res["by_category"]["coil"]["tiers"]["reviewed_priority"]
    assert proof["recall"] == 0.0 and proof["missed"] == ["e6"]
    assert coil["recall"] == 0.0 and coil["missed"] == ["e2"]


def test_delay_and_wilson():
    res = rv.evaluate(_corpus(), min_labeled=1)
    raw = res["overall"]["tiers"]["raw_sql"]
    assert raw["median_delay_h"] == 2.0 and raw["delay_samples"] == 1
    assert rv.wilson(0, 0) is None
    lo, hi = rv.wilson(2, 4)
    assert 0 < lo < 0.5 < hi < 1


def test_holdout_checks_and_claim_gate():
    res = rv.evaluate(_corpus(), min_labeled=1)
    assert res["holdout"]["chronological"] is True and res["holdout"]["equipment_holdout"] is True
    assert res["claim_supported"] is True
    strict = rv.evaluate(_corpus())  # default 20 labeled per class
    assert strict["claim_supported"] is False and "at least 20" in strict["claim_reasons"][0]
    c = _corpus()
    c["episodes"][-1].update(equipment="AHU-2", start_utc="2026-08-01T00:00:00Z")
    leak = rv.evaluate(c, min_labeled=1)
    assert leak["holdout"]["chronological"] is False and leak["holdout"]["shared_equipment"] == ["AHU-2"]
    assert leak["claim_supported"] is False


def test_validation_and_no_test_split():
    with pytest.raises(ValueError, match="label"):
        rv.evaluate({"episodes": [{"equipment": "x", "category": "c", "split": "test", "label": "maybe"}]})
    with pytest.raises(ValueError, match="split 'test'"):
        rv.evaluate({"episodes": [_ep(1, label="fault", split="train")]})


def test_cli_jsonl(tmp_path, capsys):
    p = tmp_path / "labeled.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in _corpus()["episodes"]), encoding="utf-8")
    out = tmp_path / "eval.json"
    assert rv.main([str(p), "--min-labeled", "1", "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["overall"]["device_weeks"] is None and data["overall"]["tiers"]["raw_sql"]["alerts"] == 5
    bad = tmp_path / "bad.json"
    bad.write_text('{"episodes": [{"equipment": "x"}]}', encoding="utf-8")
    assert rv.main([str(bad)]) == 2
    assert "lacks category" in capsys.readouterr().err


def test_real_reviews_compose_and_keep_the_fault():
    """Reviews written by open_fdd.ml.review feed the evaluation unchanged (fixtures from test_ml_review)."""
    import importlib.util
    from pathlib import Path

    pytest.importorskip("sklearn")
    spec = importlib.util.spec_from_file_location("_review_fixtures", Path(__file__).with_name("test_ml_review.py"))
    fx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fx)
    from open_fdd.ml.review import review_episode

    frame = fx._history()
    train = frame[frame.index < fx.CUT]
    fault = review_episode(fx._episode(), frame, train=train, training={"source": "cutoff"})
    # a healthy day after the cutoff and before the damper sticks: a SQL alert the label calls healthy
    quiet = review_episode(fx._episode("2026-01-11T00:00:00Z", "2026-01-12T00:00:00Z"), frame, train=train,
                           training={"source": "cutoff"})
    eps = [
        {"episode_id": "stuck", "equipment": "AHU-1", "category": "economizer", "split": "test", "label": "fault",
         "sql_verdict": "fault", "start_utc": "2026-01-13T00:00:00Z", "review": fault},
        {"episode_id": "other", "equipment": "AHU-1", "category": "economizer", "split": "test", "label": "healthy",
         "sql_verdict": "fault", "start_utc": "2026-01-11T00:00:00Z", "review": quiet},
    ]
    res = rv.evaluate({"device_weeks": 2, "episodes": eps}, min_labeled=1)
    raw = res["overall"]["tiers"]["raw_sql"]
    assert fault["outcome"] == "corroborated"
    assert raw["alerts"] == 2 and raw["missed"] == []  # the severe fault is never dropped from the report
    assert "stuck" not in res["overall"]["tiers"]["reviewed_priority"]["missed"]
    assert res["overall"]["review_outcomes"]["corroborated"] >= 1
    assert res["claim_supported"] is False  # no train/selection split listed: holdout not demonstrated
