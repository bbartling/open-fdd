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
from .fault_model_context import enrich_fault_alert
from .fdd_equipment import equipment_labels_for_columns
from .model_service import ModelService
from .paths import data_dir

_MODEL_CACHE: dict[str, Any] | None = None


def _model_for_fdd() -> dict[str, Any]:
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        _MODEL_CACHE = ModelService().load()
    return _MODEL_CACHE


def _fdd_alert_title(
    run: dict[str, Any],
    *,
    code: str,
    flagged: int,
    equipment_names: list[str],
) -> str:
    rule_name = str(run.get("rule_name") or "FDD rule")
    site_id = str(run.get("site_id") or "")
    if equipment_names:
        if len(equipment_names) == 1:
            who = equipment_names[0]
        else:
            who = f"{equipment_names[0]} (+{len(equipment_names) - 1} more)"
        parts = [who]
        if code:
            parts.append(code)
        parts.append(rule_name)
        return f"{' · '.join(parts)}: {flagged} fault row(s)" + (f" at {site_id}" if site_id else "")
    if code:
        return f"{code} · {rule_name}: {flagged} fault row(s)" + (f" at {site_id}" if site_id else "")
    return f"{rule_name}: {flagged} fault row(s)" + (f" at {site_id}" if site_id else "")


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
    from .fdd_equipment import enrich_fdd_run_with_equipment

    model = _model_for_fdd()
    enriched: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        site_id = str(run.get("site_id") or "").strip()
        enriched.append(enrich_fdd_run_with_equipment(dict(run), model, site_id))
    doc = {"version": 1, "generated_at": _now(), "runs": enriched}
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
    model = _model_for_fdd()
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
        site_id = str(run.get("site_id") or "").strip()
        analytics = run.get("analytics") if isinstance(run.get("analytics"), dict) else {}
        detail = str(run.get("detail") or "").strip()
        if not detail and analytics:
            detail = format_fault_detail(analytics, source=str(run.get("source") or ""))
        if not detail:
            detail = (
                f"{flagged}/{rows} samples flagged"
                f"{' (' + str(run.get('source')) + ' data)' if run.get('source') else ''}."
            )
        cols = analytics.get("flagged_columns") or analytics.get("value_columns") or []
        equipment_names = equipment_labels_for_columns(model, site_id, list(cols) if cols else None)
        issue: dict[str, Any] = {
            "id": f"fdd-{run.get('rule_id')}-{run.get('site_id')}",
            "severity": str(run.get("severity") or "warning"),
            "title": _fdd_alert_title(run, code=code, flagged=flagged, equipment_names=equipment_names),
            "detail": detail,
            "source": "fdd",
            "code": code,
            "equipment_family": str(run.get("equipment_family") or ""),
            "rule_id": str(run.get("rule_id") or ""),
            "rule_name": str(run.get("rule_name") or ""),
        }
        if equipment_names:
            issue["equipment_name"] = equipment_names[0]
            issue["equipment_names"] = equipment_names
        if analytics:
            issue["analytics"] = analytics
        issues.append(enrich_fault_alert(issue, model))
    return issues
