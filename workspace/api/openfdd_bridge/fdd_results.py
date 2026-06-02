"""Persisted output of the scheduled FDD batch run (``data/fdd_results.json``).

The batch runner writes a summary of every saved rule evaluated against every
site. :func:`fdd_issues` converts the latest summary into check-engine alert
dicts (``source="fdd"``) that :mod:`building_routes` merges into
``/api/building/status`` so faults automatically light up the building.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fdd_fault_analytics import format_fault_detail
from .paths import data_dir


def fdd_results_path() -> Path:
    return data_dir() / "fdd_results.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_results() -> dict[str, Any]:
    path = fdd_results_path()
    if not path.is_file():
        return {"version": 1, "generated_at": None, "runs": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "generated_at": None, "runs": []}
    if not isinstance(raw, dict) or not isinstance(raw.get("runs"), list):
        return {"version": 1, "generated_at": None, "runs": []}
    return raw


def save_results(runs: list[dict[str, Any]]) -> dict[str, Any]:
    doc = {"version": 1, "generated_at": _now(), "runs": runs}
    path = fdd_results_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, mode="w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    return doc


def fdd_issues() -> list[dict[str, Any]]:
    """Convert the latest batch results into check-engine alert dicts."""
    doc = load_results()
    issues: list[dict[str, Any]] = []
    for run in doc.get("runs", []):
        if not isinstance(run, dict):
            continue
        if run.get("status") == "error":
            issues.append(
                {
                    "id": f"fdd-err-{run.get('rule_id')}-{run.get('site_id')}",
                    "severity": "warning",
                    "title": f"Rule '{run.get('rule_name')}' failed on {run.get('site_id')}",
                    "detail": str(run.get("error") or "")[:2000],
                    "source": "fdd",
                    "code": str(run.get("fault_code") or ""),
                    "equipment_family": str(run.get("equipment_family") or ""),
                }
            )
            continue
        flagged = int(run.get("flagged") or 0)
        if flagged <= 0:
            continue
        rows = int(run.get("rows") or 0)
        code = str(run.get("fault_code") or "")
        analytics = run.get("analytics") if isinstance(run.get("analytics"), dict) else {}
        detail = str(run.get("detail") or "").strip()
        if not detail and analytics:
            detail = format_fault_detail(analytics, source=str(run.get("source") or ""))
        if not detail:
            detail = (
                f"{flagged}/{rows} samples flagged"
                f"{' (' + str(run.get('source')) + ' data)' if run.get('source') else ''}."
            )
        issue: dict[str, Any] = {
            "id": f"fdd-{run.get('rule_id')}-{run.get('site_id')}",
            "severity": str(run.get("severity") or "warning"),
            "title": (
                f"{code + ' · ' if code else ''}{run.get('rule_name')}: "
                f"{flagged} fault row(s) at {run.get('site_id')}"
            ),
            "detail": detail,
            "source": "fdd",
            "code": code,
            "equipment_family": str(run.get("equipment_family") or ""),
            "rule_id": str(run.get("rule_id") or ""),
            "rule_name": str(run.get("rule_name") or ""),
        }
        if analytics:
            issue["analytics"] = analytics
        issues.append(issue)
    return issues
