"""Read active FDD fault count from persisted batch results (no bridge import)."""

from __future__ import annotations

import json
from pathlib import Path


def active_fdd_fault_count(repo_root: Path) -> int:
    """Number of saved rules with flagged samples in the latest ``fdd_results.json``."""
    path = repo_root / "workspace" / "data" / "fdd_results.json"
    if not path.is_file():
        return 0
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    runs = doc.get("runs")
    if not isinstance(runs, list):
        return 0
    count = 0
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("status") == "error":
            count += 1
            continue
        flagged_raw = run.get("flagged")
        try:
            flagged_n = int(flagged_raw) if flagged_raw is not None and str(flagged_raw).strip() != "" else 0
        except (TypeError, ValueError):
            flagged_n = 0
        if flagged_n > 0:
            count += 1
    return count
