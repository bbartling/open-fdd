"""Persist AHU/RTU runtime metrics emitted by script-mode FDD rules."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import data_dir


def runtime_metrics_path() -> Path:
    return data_dir() / "runtime_metrics.json"


def load_runtime_metrics() -> dict[str, Any]:
    path = runtime_metrics_path()
    if not path.is_file():
        return {"version": 1, "updated_at": None, "sites": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "updated_at": None, "sites": {}}
    if not isinstance(raw, dict):
        return {"version": 1, "updated_at": None, "sites": {}}
    raw.setdefault("sites", {})
    return raw


def merge_run_metrics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    doc = load_runtime_metrics()
    sites = doc.setdefault("sites", {})
    updated = False
    for run in runs:
        if not isinstance(run, dict):
            continue
        metrics = run.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            continue
        site_id = str(run.get("site_id") or metrics.get("site_id") or "").strip()
        if not site_id:
            continue
        equipment_id = str(metrics.get("equipment_id") or run.get("equipment_id") or "default").strip()
        site_bucket = sites.setdefault(site_id, {})
        site_bucket[equipment_id] = {
            **metrics,
            "rule_id": str(run.get("rule_id") or ""),
            "rule_name": str(run.get("rule_name") or ""),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        updated = True
    if not updated:
        return doc
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = runtime_metrics_path()
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
