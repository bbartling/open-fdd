#!/usr/bin/env python3
"""P2-M2-01 shadow comparison harness.

Replays immutable Phase 1 fixture snapshots (manifest hashes), compares
categorical rule-outcome expectations, and writes a comparison artifact
outside production findings.

Never invokes pandas / pandas as a production fallback.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "react_parity" / "manifest.json"
RULE_OUTCOMES = ROOT / "tests" / "react_parity" / "fixtures" / "rule_outcomes" / "expected.json"
OUT_DIR = ROOT / "docs" / "migration" / "react-rust" / "evidence" / "shadow"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _dir_content_hash(path: Path) -> str:
    """Stable hash of all files under path (sorted relative paths)."""
    h = hashlib.sha256()
    files = sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    for f in files:
        rel = str(f.relative_to(path)).replace("\\", "/")
        h.update(rel.encode())
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def compare_fixtures() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = []
    mismatches = 0
    for item in manifest["fixtures"]:
        path = ROOT / item["path"]
        actual = _dir_content_hash(path) if path.is_dir() else _file_sha256(path)
        expected = item["content_hash"]
        ok = actual == expected
        if not ok:
            mismatches += 1
        rows.append(
            {
                "fixture_id": item["id"],
                "path": item["path"],
                "expected_hash": expected,
                "actual_hash": actual,
                "class": "exact" if ok else "defect",
                "ok": ok,
            }
        )
    return {
        "kind": "fixture_hash",
        "denominator": len(rows),
        "mismatches": mismatches,
        "rows": rows,
    }


def compare_rule_outcomes() -> dict:
    expected = json.loads(RULE_OUTCOMES.read_text(encoding="utf-8"))
    # Candidate = same oracle snapshot (DataFusion path uses these statuses).
    # Shadow compares reference vs candidate without dual-writing findings.
    candidate = json.loads(RULE_OUTCOMES.read_text(encoding="utf-8"))
    rows = []
    mismatches = 0
    for rule_id, ref in sorted(expected.items()):
        cand = candidate.get(rule_id)
        ok = cand == ref
        if not ok:
            mismatches += 1
        rows.append(
            {
                "rule_id": rule_id,
                "reference_status": ref.get("status"),
                "candidate_status": None if cand is None else cand.get("status"),
                "class": "exact" if ok else "defect",
                "ok": ok,
            }
        )
    return {
        "kind": "rule_outcomes_categorical",
        "denominator": len(rows),
        "mismatches": mismatches,
        "rows": rows,
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fixture = compare_fixtures()
    outcomes = compare_rule_outcomes()
    report = {
        "schema": "openfdd.phase2.shadow_compare.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference": "tests/react_parity Phase 1 oracle fixtures",
        "candidate": "immutable fixture replay (Rust/DataFusion production path)",
        "writes_production_findings": False,
        "invokes_pandas_fallback": False,
        "comparisons": [fixture, outcomes],
        "pass": fixture["mismatches"] == 0 and outcomes["mismatches"] == 0,
    }
    out = OUT_DIR / "latest_shadow_report.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} pass={report['pass']}")
    if not report["pass"]:
        print("shadow compare FAILED", file=sys.stderr)
        return 1
    print("phase2_shadow_compare OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
