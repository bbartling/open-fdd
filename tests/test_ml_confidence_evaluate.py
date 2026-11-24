"""Evaluation harness: synthetic planted-fault benchmark and --evaluate CLI."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from open_fdd.ml.confidence import ConfidenceConfig, main
from open_fdd.ml.confidence_evaluate import (
    TRUE_CLASSES,
    class_labels,
    evaluate_benchmark,
    make_benchmark,
    to_markdown,
    write_benchmark,
)


def test_benchmark_plants_all_four_cases_across_equipment():
    bench = make_benchmark(units_per_case=3, days=6, seed=7)
    counts = bench.cases["case"].value_counts().to_dict()
    for case in ("real", "real_gap", "stale", "stale_partial", "off", "clean"):
        assert counts.get(case, 0) >= 1, counts
    assert not bench.cases["equipment_id"].duplicated().any()
    assert set(bench.labels["label"]) == {"fault", "false_positive", "tuning"}
    assert {"R-SAT-HIGH", "R-COIL"} <= set(bench.flags["rule_id"])
    assert {"R-TIGHT", "R-MED"} & set(bench.flags["rule_id"])
    # each planted SAT window actually trips the rule
    for row in bench.labels.itertuples():
        if row.rule_id == "R-TIGHT":
            continue
        hit = bench.flags[(bench.flags["equipment_id"] == row.equipment_id) & (bench.flags["rule_id"] == row.rule_id)
                          & (bench.flags["timestamp"] >= row.start_ts) & (bench.flags["timestamp"] <= row.end_ts)]
        assert hit["flag"].any(), (row.equipment_id, row.rule_id)


def test_evaluate_improves_precision_and_reduces_false_positives():
    _, _, report = evaluate_benchmark(ConfidenceConfig(), seed=7, units_per_case=5, days=8)
    assert report["status"] == "ok"
    assert report["labeled_episodes"] >= 20
    assert report["truth"]["real"] >= 5
    assert report["truth"]["false_positive"] >= 5
    assert report["truth"]["tuning"] >= 10
    # screening should keep most real faults and drop many non-real flags
    op = report["operational"]
    assert op["screen"]["precision"] > op["rule"]["precision"]
    assert op["screen"]["recall"] >= 0.8
    at90 = next(r for r in op["false_positive_reduction"] if r["target_recall"] == 0.9)
    assert at90["achieved"] and at90["false_positive_reduction"] >= 0.3
    # 3-class confusion covers every true class
    conf = report["confusion"]
    assert conf["rows"] == list(TRUE_CLASSES)
    for i, cls in enumerate(TRUE_CLASSES):
        assert sum(conf["counts"][i]) == report["truth"][cls]
    cal = report["calibration"]["heuristic"]
    assert set(cal) == {"brier", "ece", "auc"}
    assert cal["auc"] >= 0.8
    md = to_markdown(report)
    assert "Precision and recall" in md and "False-positive reduction" in md and "Brier" in md


def test_planted_cases_go_to_the_expected_screen_labels():
    bench, result, report = evaluate_benchmark(ConfidenceConfig(), seed=7, units_per_case=5, days=8)
    by = report["labels_by_truth"]
    # real faults (including a brief history gap) stay likely_real; stale and off go to likely_false_positive
    assert by["real"]["likely_real"] >= 0.8 * sum(by["real"].values())
    assert by["false_positive"]["likely_false_positive"] >= by["false_positive"]["likely_real"]
    if sum(by["tuning"].values()):
        assert by["tuning"]["tuning_suggested"] >= 0.5 * sum(by["tuning"].values())
    ep = result["episodes"].copy()
    ep["truth"] = class_labels(ep, bench.labels)
    ep["case"] = ep["equipment_id"].map(bench.cases.set_index("equipment_id")["case"])
    real = ep[ep["truth"] == "real"]
    assert (real["label"] == "likely_real").mean() >= 0.8, real.groupby("case")["label"].value_counts().to_dict()
    gap = ep[(ep["case"] == "real_gap") & (ep["rule_id"] == "R-SAT-HIGH") & (ep["truth"] == "real")]
    assert not gap.empty and (gap["label"] == "likely_real").all(), gap[["label", "reason", "dq_gap"]].to_dict("records")
    for case in ("stale", "stale_partial", "off"):
        rows = ep[(ep["case"] == case) & (ep["rule_id"] == "R-SAT-HIGH") & (ep["truth"] == "false_positive")]
        assert not rows.empty and (rows["label"] == "likely_false_positive").all(), (
            case, rows["label"].tolist(), rows["reason"].tolist(), rows["dq_stale"].tolist(),
        )


def test_class_labels_rule_specific_precedes_rule_agnostic():
    ep = pd.DataFrame({
        "equipment_id": ["A", "A"], "rule_id": ["R1", "R2"],
        "start": pd.to_datetime(["2026-03-01T00:00Z", "2026-03-01T00:00Z"], utc=True),
        "end": pd.to_datetime(["2026-03-01T06:00Z", "2026-03-01T06:00Z"], utc=True),
    })
    lab = pd.DataFrame({
        "equipment_id": ["A", "A"],
        "start_ts": pd.to_datetime(["2026-03-01T00:00Z", "2026-03-01T00:00Z"], utc=True),
        "end_ts": pd.to_datetime(["2026-03-01T06:00Z", "2026-03-01T12:00Z"], utc=True),
        "rule_id": ["R1", np.nan],
        "label": ["fault", "tuning"],
    })
    got = class_labels(ep, lab)
    assert got.tolist() == ["real", "tuning"]


def test_evaluate_cli_synthetic_writes_report(tmp_path):
    assert main(["--evaluate", "--seeds", "7", "--units-per-case", "3", "--out-dir", str(tmp_path / "o"),
                 "--write-benchmark", str(tmp_path / "bench"), "--print", "none"]) == 0
    ev = json.loads((tmp_path / "o" / "evaluation.json").read_text())
    assert ev["status"] == "ok"
    assert ev["operational"]["screen"]["precision"] > ev["operational"]["rule"]["precision"]
    assert (tmp_path / "o" / "evaluation.md").is_file()
    assert (tmp_path / "bench" / "flags.csv").is_file()
    labels = pd.read_csv(tmp_path / "bench" / "labels.csv")
    assert set(labels["label"]) == {"fault", "false_positive", "tuning"}


def test_evaluate_cli_on_user_flags_needs_labels(tmp_path):
    bench = make_benchmark(units_per_case=2, days=6, seed=1)
    write_benchmark(bench, tmp_path / "b")
    with pytest.raises(ValueError, match="--labels"):
        main(["--evaluate", "--flags", str(tmp_path / "b" / "flags.csv"),
              "--history", str(tmp_path / "b" / "history.csv"),
              "--out-dir", str(tmp_path / "o"), "--print", "none"])
    assert main(["--evaluate", "--flags", str(tmp_path / "b" / "flags.csv"),
                 "--history", str(tmp_path / "b" / "history.csv"),
                 "--labels", str(tmp_path / "b" / "labels.csv"),
                 "--out-dir", str(tmp_path / "o"), "--print", "none"]) == 0
    ev = json.loads((tmp_path / "o" / "evaluation.json").read_text())
    assert ev["status"] == "ok" and ev["labeled_episodes"] > 0


def test_evaluate_suite_reports_mean_and_spread():
    from open_fdd.ml.confidence_evaluate import evaluate_suite

    bundle = evaluate_suite((7, 11, 19), ConfidenceConfig(), units_per_case=3, days=6)
    su = bundle["summary"]
    assert su["n"] == 3
    assert su["operational_screen_recall"]["mean"] >= 0.8
    assert su["operational_screen_precision"]["mean"] > su["operational_rule_precision"]["mean"]
    assert su["real_as_likely_real"]["mean"] >= 0.8
    assert su["false_positive_as_likely_false_positive"]["min"] >= 0.5
    # spread is reported (std may be zero if all seeds agree)
    assert "std" in su["operational_screen_precision"]
    assert "_bench" in bundle and bundle["_result"]["episodes"] is not None
