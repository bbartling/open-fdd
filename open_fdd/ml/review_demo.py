"""Synthetic end-to-end demo of the episode review workflow (#1667 acceptance 6), runnable from an installed wheel.

    python -m open_fdd.ml.review_demo ./review-demo

writes a generic synthetic SI device folder, two saved SQL episodes, the review of each, a labeled corpus and its
evaluation, then prints a short summary. Everything is synthetic (seeded); no NF, database or network is used.

* ``AHU-DEMO/``: 10 days of 5-minute AHU history; the outside-air damper sticks at minimum from day 8. The fan is
  off from 00:00 to 05:00 UTC every day, so the review's run-proof gate drops those rows from training and scoring.
* ``episodes/stuck.json``: a SQL fault on the stuck days (labeled ``fault`` in the corpus).
* ``episodes/healthy_day.json``: a SQL alert on a healthy day after the training cutoff (labeled ``healthy``).
* ``reviews/*.json``: ``open_fdd.ml.review`` output, trained on rows before the cutoff (an operator assertion).
* ``labeled.json`` and ``eval.json``: the ``open_fdd.ml.review_eval`` input and output.

Two episodes cannot support a claim, so ``eval.json`` reports ``claim_supported: false``; the demo shows the shape
of the workflow, not a performance figure. ``OUT`` must be empty or new (``--force`` writes into a non-empty one).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DAY = 288  # 5-minute rows
OFF_ROWS_PER_DAY = 60  # 00:00-05:00 UTC
#: test-period exposure: AHU-DEMO is monitored from the cutoff (2026-01-11) to the end of the history (2026-01-15)
TEST_DEVICE_WEEKS = {"AHU-DEMO": round(4 / 7, 4)}
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
    return_air_temperature = 22 + rng.normal(0, 0.2, n)
    damper = np.clip(0.1 + 0.8 * (oat < 15) * (oat > 2), 0.1, 1.0)
    actual = damper.copy()
    if stuck_from_day is not None:
        actual[stuck_from_day * DAY:] = 0.1
    mixed_air_temperature = actual * oat + (1 - actual) * return_air_temperature + rng.normal(0, 0.1, n)
    valve = np.clip((mixed_air_temperature - 13) / 10, 0, 1)
    discharge_air_temperature = mixed_air_temperature - 10 * valve + rng.normal(0, 0.1, n)
    fan = np.where((np.arange(n) % DAY) < OFF_ROWS_PER_DAY, 0.0, 1.0)  # off 00:00-05:00 UTC daily
    return pd.DataFrame({
        "discharge_air_temperature": discharge_air_temperature, "discharge_air_temperature_setpoint": 13.0, "mixed_air_temperature": mixed_air_temperature, "return_air_temperature": return_air_temperature,
        "outdoor_air_intake_temperature": oat, "outdoor_air_intake_damper_position_command": damper, "cooling_valve_position_command": valve,
        "supply_fan_command": (0.7 + 0.1 * valve) * fan, "supply_fan_operating_status": fan, "occupancy_status": 1.0,
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


def run_demo(out: Path, methods: str = "grey_box,pca", *, force: bool = False) -> dict:
    from open_fdd.ml import review, review_eval
    from open_fdd.ml.cli import role_frame_from_folder

    if out.exists() and any(out.iterdir()) and not force:
        raise ValueError(f"{out} is not empty; give an empty or new directory, or --force to overwrite the demo files")
    out.mkdir(parents=True, exist_ok=True)
    paths = write_fixture(out)
    (out / "reviews").mkdir(exist_ok=True)
    frame = role_frame_from_folder(paths["folder"])
    cut = review._utc(CUTOFF, "cutoff")
    train = frame[frame.index < cut]
    chosen = tuple(m.strip().lower().replace("-", "_") for m in methods.split(",") if m.strip())
    episodes = []
    for name, (start, _end, label) in EPISODES.items():
        rpath = out / "reviews" / f"{name}.json"
        training = {"source": "cutoff", "cutoff_utc": str(cut),
                    "assertion": "operator-asserted known-good (not an independently verified maintenance label)"}
        rec = review.review_episode(review.load_episode(paths[name]), frame, train=train, training=training,
                                    methods=chosen)
        rec["inputs"] = {"episode_sha256": review._sha256(paths[name]),
                         "folder": review._folder_fingerprint(paths["folder"])}
        rpath.write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
        episodes.append({"episode_id": name, "equipment": "AHU-DEMO", "category": "economizer", "split": "test",
                         "label": label, "label_source": "synthetic fixture (known by construction)",
                         "sql_verdict": "fault", "start_utc": start, "sql_start_utc": start,
                         "review": json.loads(rpath.read_text(encoding="utf-8"))})
    corpus = {"test_device_weeks": TEST_DEVICE_WEEKS, "episodes": episodes}
    (out / "labeled.json").write_text(json.dumps(corpus, indent=1, default=str), encoding="utf-8")
    result = review_eval.evaluate(corpus, min_labeled=20)
    (out / "eval.json").write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    tiers = result["overall"]["tiers"]
    return {
        "out": str(out),
        "outcomes": {e["episode_id"]: e["review"]["outcome"] for e in episodes},
        "active_rows": {e["episode_id"]: e["review"]["window"]["active_rows"] for e in episodes},
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
    p.add_argument("--force", action="store_true", help="write into a non-empty OUT (overwrites the demo files)")
    args = p.parse_args(argv)
    try:
        summary = run_demo(args.out, args.methods, force=args.force)
    except (RuntimeError, ValueError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
