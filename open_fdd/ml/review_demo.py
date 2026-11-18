"""Synthetic end-to-end demo of the episode review workflow (#1667 acceptance 6), runnable from an installed wheel.

    python -m open_fdd.ml.review_demo ./review-demo

writes a generic synthetic SI device folder, two saved SQL episodes, the review of each, a labeled corpus and its
evaluation, then prints a short summary. Everything is synthetic (seeded); no NF, database or network is used.

* ``AHU-DEMO/``: 10 days of 5-minute AHU history; the outside-air damper sticks at minimum from day 8.
* ``episodes/stuck.json``: a SQL fault on the stuck days (labeled ``fault`` in the corpus).
* ``episodes/healthy_day.json``: a SQL alert on a healthy day after the training cutoff (labeled ``healthy``).
* ``reviews/*.json``: ``open_fdd.ml.review`` output, trained on rows before the cutoff (an operator assertion).
* ``labeled.json`` and ``eval.json``: the ``open_fdd.ml.review_eval`` input and output.

Two episodes cannot support a claim, so ``eval.json`` reports ``claim_supported: false``; the demo shows the shape
of the workflow, not a performance figure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DAY = 288  # 5-minute rows
CUTOFF = "2026-01-11T00:00:00Z"
EPISODES = {
    "stuck": ("2026-01-13T00:00:00Z", "2026-01-14T00:00:00Z", "fault"),
    "healthy_day": ("2026-01-11T00:00:00Z", "2026-01-12T00:00:00Z", "healthy"),
}


def synthetic_ahu(days: int = 10, stuck_from_day: int | None = 7, seed: int = 0):
    """Seeded AHU frame (SI, role columns) obeying the mixed-air balance and a simple coil model."""
    import numpy as np
    import pandas as pd

    n = days * DAY
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    oat = 10 + 12 * np.sin(np.arange(n) / DAY * 2 * np.pi) + rng.normal(0, 0.3, n)
    rat = 22 + rng.normal(0, 0.2, n)
    damper = np.clip(0.1 + 0.8 * (oat < 15) * (oat > 2), 0.1, 1.0)
    actual = damper.copy()
    if stuck_from_day is not None:
        actual[stuck_from_day * DAY:] = 0.1
    mat = actual * oat + (1 - actual) * rat + rng.normal(0, 0.1, n)
    valve = np.clip((mat - 13) / 10, 0, 1)
    sat = mat - 10 * valve + rng.normal(0, 0.1, n)
    return pd.DataFrame({
        "discharge-air-temp": sat, "discharge-air-temp-sp": 13.0, "mixed-air-temp": mat, "return-air-temp": rat,
        "outside-air-temp": oat, "outside-air-damper": damper, "cooling-valve": valve, "fan-cmd": 0.7 + 0.1 * valve,
        "fan-status": 1.0, "occupied": 1.0,
    }, index=idx)


def write_fixture(out: Path) -> dict[str, Path]:
    """Write the device folder and the two saved SQL episodes; return their paths."""
    folder = out / "AHU-DEMO"
    folder.mkdir(parents=True, exist_ok=True)
    frame = synthetic_ahu()
    frame.to_csv(folder / "history_wide.csv", index_label="timestamp_utc")
    (folder / "column_map.json").write_text(
        json.dumps({"equipType": "AHU", "points": {c: c for c in frame.columns}}, indent=1), encoding="utf-8")
    paths = {"folder": folder}
    (out / "episodes").mkdir(exist_ok=True)
    for name, (start, end, _label) in EPISODES.items():
        p = out / "episodes" / f"{name}.json"
        p.write_text(json.dumps({"rule_id": "ECON-STUCK-DEMO", "verdict": "fault", "site_id": "demo-site",
                                 "equipment_id": "AHU-DEMO", "start_utc": start, "end_utc": end,
                                 "tuners": {"damper_min_fraction": 0.1}}, indent=1), encoding="utf-8")
        paths[name] = p
    return paths


def run_demo(out: Path, methods: str = "grey_box,pca") -> dict:
    from open_fdd.ml import review, review_eval

    out.mkdir(parents=True, exist_ok=True)
    paths = write_fixture(out)
    (out / "reviews").mkdir(exist_ok=True)
    episodes = []
    for name, (start, _end, label) in EPISODES.items():
        rpath = out / "reviews" / f"{name}.json"
        code = review.main([str(paths[name]), str(paths["folder"]), "--train-until", CUTOFF, "--methods", methods,
                            "--out", str(rpath)])
        if code != 0:
            raise RuntimeError(f"review of {name} exited {code}")
        episodes.append({"episode_id": name, "equipment": "AHU-DEMO", "category": "economizer", "split": "test",
                         "label": label, "label_source": "synthetic fixture (known by construction)",
                         "sql_verdict": "fault", "start_utc": start, "sql_start_utc": start,
                         "review": json.loads(rpath.read_text(encoding="utf-8"))})
    corpus = {"device_weeks": round(10 / 7, 4), "episodes": episodes}
    (out / "labeled.json").write_text(json.dumps(corpus, indent=1, default=str), encoding="utf-8")
    result = review_eval.evaluate(corpus, min_labeled=20)
    (out / "eval.json").write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    tiers = result["overall"]["tiers"]
    return {
        "out": str(out),
        "outcomes": {e["episode_id"]: e["review"]["outcome"] for e in episodes},
        "raw_sql_alerts": tiers["raw_sql"]["alerts"],
        "reviewed_priority_alerts": tiers["reviewed_priority"]["alerts"],
        "missed_faults_raw_sql": tiers["raw_sql"]["missed"],
        "reviewer_workload": result["overall"]["reviewer_workload"],
        "claim_supported": result["claim_supported"],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m open_fdd.ml.review_demo", description=__doc__.split("\n\n")[0])
    p.add_argument("out", type=Path, help="empty or new directory for the demo files")
    p.add_argument("--methods", default="grey_box,pca", help="review methods (default grey_box,pca)")
    args = p.parse_args(argv)
    try:
        summary = run_demo(args.out, args.methods)
    except (RuntimeError, ValueError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
