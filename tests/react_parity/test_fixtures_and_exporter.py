"""P1-M1 — react parity fixture catalog + reference exporter."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests" / "react_parity" / "manifest.json"
EXPORTER = ROOT / "tools" / "react_parity" / "export_reference_json.py"
REQUIRED = {
    "clean_single_equip",
    "multi_equip_package",
    "missing_role",
    "dup_timestamps",
    "irregular_sampling",
    "unit_mismatch",
    "empty_interval",
    "hostile_zip",
    "partial_weather",
    "rule_outcomes",
    "job_full",
    "wattlab_v3",
}


def test_manifest_covers_required_fixtures() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ids = {f["id"] for f in data["fixtures"]}
    assert REQUIRED <= ids
    for item in data["fixtures"]:
        path = ROOT / item["path"]
        assert path.is_dir(), path
        assert len(item["content_hash"]) == 64


def test_reference_exporter_is_byte_stable(tmp_path: Path) -> None:
    payload = tmp_path / "payload.json"
    payload.write_text(
        json.dumps({"b": 2, "a": [3, 1], "z": float("nan")}, allow_nan=True),
        encoding="utf-8",
    )
    outs = []
    for i in range(3):
        out = tmp_path / f"ref{i}.json"
        subprocess.check_call(
            [
                sys.executable,
                str(EXPORTER),
                "--fixture-id",
                "clean_single_equip",
                "--fixture-hash",
                "abc",
                "--capability",
                "CAP-UPLOAD",
                "--payload-json",
                str(payload),
                "-o",
                str(out),
            ],
            cwd=ROOT,
        )
        outs.append(out.read_bytes())
    assert outs[0] == outs[1] == outs[2]
    body = json.loads(outs[0])
    assert body["schema"].startswith("openfdd.react_parity.reference")
    assert list(body["payload"].keys()) == ["a", "b", "z"]
