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
from .fdd_equipment import (
    enrich_fdd_run_with_equipment,
    equipment_labels_for_columns,
    plain_symptom_from_rule_name,
)
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
    flagged: int,
    equipment_names: list[str],
) -> str:
    """Equipment-first title; fault code is not repeated in the headline."""
    symptom = str(run.get("short_description") or run.get("symptom") or "").strip()
    if not symptom:
        symptom = plain_symptom_from_rule_name(str(run.get("rule_name") or "FDD rule"))
    site_id = str(run.get("site_id") or "")
    if equipment_names:
        if len(equipment_names) == 1:
            who = equipment_names[0]
        else:
            who = f"{equipment_names[0]} (+{len(equipment_names) - 1} more)"
        title = f"{who} — {symptom}"
    else:
        title = symptom
    if flagged > 0:
        title += f" ({flagged} samples)"
    if site_id:
        title += f" at {site_id}"
    return title


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
    for raw_run in doc.get("runs", []):
        if not isinstance(raw_run, dict):
            continue
        site_id = str(raw_run.get("site_id") or "").strip()
        run = enrich_fdd_run_with_equipment(dict(raw_run), model, site_id)
        if run.get("status") == "error":
            issues.append(
                {
                    "id": f"fdd-err-{run.get('rule_id')}-{run.get('site_id')}",
                    "severity": "warning",
                    "title": f"Rule '{run.get('rule_name')}' failed on {run.get('site_id')}",
                    "detail": str(run.get("error") or "")[:2000],
                    "source": "fdd",
                    "rule_id": str(run.get("rule_id") or ""),
                    "rule_name": str(run.get("rule_name") or ""),
                    "short_description": str(run.get("short_description") or run.get("rule_name") or ""),
                }
            )
            continue
        flagged = int(run.get("flagged") or 0)
        if flagged <= 0:
            continue
        rows = int(run.get("rows") or 0)
        site_id = str(run.get("site_id") or "").strip()
        short_desc = str(run.get("short_description") or run.get("rule_name") or "").strip()
        analytics = run.get("analytics") if isinstance(run.get("analytics"), dict) else {}
        detail = str(run.get("detail") or "").strip()
        if not detail and analytics:
            detail = format_fault_detail(analytics, source=str(run.get("source") or ""))
        if not detail:
            src_label = str(run.get("source") or "").strip()
            if src_label == "demo" and site_id and site_id not in {"demo", "site", "test", "sample"}:
                src_label = "historian (demo fallback — check feather ingest)"
            detail = (
                f"{flagged}/{rows} samples flagged"
                f"{' (' + src_label + ')' if src_label else ''}."
            )
        cols = analytics.get("flagged_columns") or analytics.get("value_columns") or []
        equipment_names = list(run.get("equipment_names") or [])
        if not equipment_names:
            equipment_names = equipment_labels_for_columns(model, site_id, list(cols) if cols else None)
        rule_id = str(run.get("rule_id") or "")
        issue: dict[str, Any] = {
            "id": f"fdd-{rule_id}-{site_id}",
            "severity": str(run.get("severity") or "warning"),
            "title": _fdd_alert_title(run, flagged=flagged, equipment_names=equipment_names),
            "detail": detail,
            "source": "fdd",
            "code": rule_id,
            "rule_id": rule_id,
            "rule_name": str(run.get("rule_name") or ""),
            "short_description": short_desc,
        }
        if equipment_names:
            issue["equipment_name"] = equipment_names[0]
            issue["equipment_names"] = equipment_names
        if run.get("equipment_id"):
            issue["equipment_id"] = run.get("equipment_id")
        if run.get("data_source"):
            issue["data_source"] = run.get("data_source")
        if run.get("symptom"):
            issue["symptom"] = run.get("symptom")
        if analytics:
            issue["analytics"] = analytics
        enriched = enrich_fault_alert(issue, model)
        ctx = enriched.get("model_context") if isinstance(enriched.get("model_context"), dict) else {}
        ctx_eq = ctx.get("equipment") if isinstance(ctx.get("equipment"), dict) else {}
        eq_name = str(ctx_eq.get("name") or enriched.get("equipment_name") or "").strip()
        eq_id = str(ctx_eq.get("id") or enriched.get("equipment_id") or "").strip()
        if eq_name and eq_name.lower() not in {"not mapped"}:
            enriched["equipment_name"] = eq_name
            if eq_name not in (enriched.get("title") or ""):
                symptom = str(enriched.get("short_description") or enriched.get("symptom") or "").strip()
                if symptom:
                    enriched["title"] = f"{eq_name} — {symptom}"
        if eq_id:
            enriched["equipment_id"] = eq_id
        issues.append(enriched)
    return issues
