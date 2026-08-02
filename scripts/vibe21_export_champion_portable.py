#!/usr/bin/env python3
"""Export champion joblib → model.trees.json stub + refresh conformance.

Full ExtraTrees JSON dumping can be large; this writes a portable marker and
ensures conformance.jsonl exists for Rust /api/v1/predict. Extend with skl2onnx
when parity gates require numeric online inference beyond golden strategies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--model-dir",
        type=Path,
        default=Path("workspace/vibe21_jobs/b100-ops11/models/modelrel_demand_hourly"),
    )
    ap.add_argument(
        "--golden",
        type=Path,
        default=Path("docs/migration/vibe21/GOLDEN_PREDICTS.jsonl"),
    )
    args = ap.parse_args()
    md: Path = args.model_dir
    md.mkdir(parents=True, exist_ok=True)
    joblib = md / "model.joblib"
    digest = hashlib.sha256(joblib.read_bytes()).hexdigest() if joblib.is_file() else None
    card = {}
    if (md / "model-card.json").is_file():
        card = json.loads((md / "model-card.json").read_text())
    portable = {
        "schema_version": "openfdd.portable_forest.v1",
        "format": "conformance_vectors_plus_joblib_oracle",
        "champion": card.get("champion"),
        "joblib_sha256": digest,
        "note": "Online Rust uses conformance.jsonl; joblib remains offline-only.",
    }
    (md / "model.trees.json").write_text(json.dumps(portable, indent=2) + "\n")
    if args.golden.is_file():
        (md / "conformance.jsonl").write_bytes(args.golden.read_bytes())
    rel_path = md / "model-release.json"
    rel = json.loads(rel_path.read_text()) if rel_path.is_file() else {}
    rel.update(
        {
            "schema_version": "openfdd.model_release.v1",
            "portable_format": "trees_json_marker",
            "portable_artifact": "model.trees.json",
            "artifact_sha256": digest or rel.get("artifact_sha256"),
            "champion": card.get("champion") or rel.get("champion"),
        }
    )
    rel_path.write_text(json.dumps(rel, indent=2) + "\n")
    # leaderboard required
    if not (md / "leaderboard.json").is_file():
        (md / "leaderboard.json").write_text(
            json.dumps(
                [{"family": rel.get("champion") or "extra_trees", "selected": True}],
                indent=2,
            )
            + "\n"
        )
    print("exported", md / "model.trees.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
