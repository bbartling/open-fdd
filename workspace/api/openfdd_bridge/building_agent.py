"""Building agent check-in — poll health, faults, logs, memory (API-only, no SSH)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .building_status import collect_status
from .device_poll_health import get_device_poll_snapshot
from .fdd_results import load_results
from .fdd_runner import run_batch
from .fdd_tuning import build_tuning_brief
from .ops_logs import collect_ops_logs
from .poll_throughput import compute_poll_throughput
from .site_defaults import ensure_default_site
from .site_memory import append_checkin_note, get_site_memory
from .model_service import ModelService
from .ttl_service import TtlService

_CHECKIN_STATE = "building_agent_checkin.json"


def _state_path() -> Path:
    from .paths import data_dir

    return data_dir() / _CHECKIN_STATE


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {"version": 1, "runs": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "runs": []}
    return raw if isinstance(raw, dict) else {"version": 1, "runs": []}


def _save_state(doc: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _resolve_site_id(site_id: str | None) -> str:
    if site_id and str(site_id).strip():
        return str(site_id).strip()
    return ensure_default_site(ModelService(), TtlService())


def _fdd_summary(*, site_id: str) -> dict[str, Any]:
    doc = load_results()
    runs = [r for r in doc.get("runs", []) if isinstance(r, dict)]
    site_runs = [r for r in runs if str(r.get("site_id") or "") in {"", site_id}]
    flagged = [r for r in site_runs if int(r.get("flagged") or 0) > 0]
    errors = [r for r in site_runs if r.get("status") == "error"]
    tuning_candidates: list[dict[str, Any]] = []
    for run in flagged:
        rows = int(run.get("rows") or 0)
        flagged_n = int(run.get("flagged") or 0)
        if rows <= 0:
            continue
        pct = round(100.0 * flagged_n / rows, 1)
        if pct >= 85.0:
            tuning_candidates.append(
                {
                    "rule_id": run.get("rule_id"),
                    "rule_name": run.get("rule_name"),
                    "flagged_pct": pct,
                    "fault_code": run.get("fault_code"),
                    "analytics": run.get("analytics"),
                    "hint": "High flag rate — review bounds before auto-tune",
                }
            )
    return {
        "generated_at": doc.get("generated_at"),
        "runs_total": len(site_runs),
        "runs_flagged": len(flagged),
        "runs_error": len(errors),
        "tuning_candidates": tuning_candidates[:12],
        "recent_flagged": flagged[:8],
        "recent_errors": errors[:6],
    }


def _actions_from_snapshot(
    *,
    throughput: dict[str, Any],
    building: dict[str, Any],
    ops: dict[str, Any],
    fdd: dict[str, Any],
    auto_tune: bool,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    keepup = throughput.get("keepup_ratio")
    if throughput.get("status") in {"lagging", "error"}:
        actions.append(
            {
                "kind": "poll_degraded",
                "severity": "critical" if throughput.get("status") == "error" else "warning",
                "detail": f"Poll keepup_ratio={keepup} status={throughput.get('status')}",
            }
        )
    if (ops.get("summary") or {}).get("has_bridge_errors"):
        actions.append(
            {
                "kind": "bridge_errors",
                "severity": "warning",
                "detail": f"bridge_error_count={(ops.get('summary') or {}).get('bridge_error_count')}",
            }
        )
    for cand in fdd.get("tuning_candidates") or []:
        actions.append(
            {
                "kind": "rule_tune_review",
                "severity": "info",
                "rule_id": cand.get("rule_id"),
                "detail": f"{cand.get('rule_name')} flagged {cand.get('flagged_pct')}%",
                "auto_tune_eligible": bool(auto_tune and (keepup is None or keepup >= 0.85)),
            }
        )
    alert_n = len(building.get("alerts") or [])
    if alert_n:
        actions.append({"kind": "active_alerts", "severity": "info", "detail": f"{alert_n} alert(s) on check-engine"})
    return actions


def run_checkin(
    *,
    site_id: str | None = None,
    run_fdd_batch: bool = True,
    write_memory: bool = True,
    window_minutes: int = 60,
) -> dict[str, Any]:
    """Single building check-in cycle (callable from REST or cron)."""
    sid = _resolve_site_id(site_id)
    auto_tune = os.environ.get("OFDD_AGENT_AUTO_TUNE", "").strip().lower() in {"1", "true", "yes"}

    batch_result: dict[str, Any] | None = None
    if run_fdd_batch:
        try:
            batch_result = run_batch(limit=500)
        except Exception as exc:  # noqa: BLE001
            batch_result = {"ok": False, "error": str(exc)[:500]}

    throughput = compute_poll_throughput(window_minutes=window_minutes)
    building = collect_status()
    poll_health = get_device_poll_snapshot(site_id=sid, force=True)
    ops = collect_ops_logs(tail=100, include_docker=True)
    fdd = _fdd_summary(site_id=sid)
    tuning = build_tuning_brief(site_id=sid, window_minutes=window_minutes)
    memory = get_site_memory(site_id=sid, kind="memory")

    actions = _actions_from_snapshot(
        throughput=throughput,
        building=building,
        ops=ops,
        fdd=fdd,
        auto_tune=auto_tune,
    )

    summary_parts = [
        f"Poll {throughput.get('status')} keepup={throughput.get('keepup_ratio')}",
        f"enabled={throughput.get('enabled_points')} obs/min={throughput.get('observed_samples_per_min')}",
        f"FDD flagged={fdd.get('runs_flagged')}/{fdd.get('runs_total')}",
        f"alerts={len(building.get('alerts') or [])}",
    ]
    if (ops.get("summary") or {}).get("has_bridge_errors"):
        summary_parts.append("bridge errors present")
    summary = "; ".join(summary_parts)

    detail_lines = []
    for act in actions[:8]:
        detail_lines.append(f"- [{act.get('severity')}] {act.get('kind')}: {act.get('detail')}")
    if tuning.get("recommendations"):
        detail_lines.append("\n**FDD tuning brief:**")
        for rec in tuning["recommendations"][:6]:
            detail_lines.append(
                f"- [{rec.get('priority')}] {rec.get('rule_name') or rec.get('kind')}: {rec.get('detail')}"
            )
    elif fdd.get("tuning_candidates"):
        detail_lines.append("\n**Tuning candidates (human review):**")
        for c in fdd["tuning_candidates"][:5]:
            detail_lines.append(f"- {c.get('rule_name')} ({c.get('flagged_pct')}% flagged)")

    memory_result = None
    if write_memory:
        memory_result = append_checkin_note(
            site_id=sid,
            summary=summary,
            detail="\n".join(detail_lines),
        )

    run_doc = {
        "at": datetime.now(timezone.utc).isoformat(),
        "site_id": sid,
        "summary": summary,
        "throughput_status": throughput.get("status"),
        "keepup_ratio": throughput.get("keepup_ratio"),
        "actions_count": len(actions),
    }
    state = _load_state()
    runs = state.setdefault("runs", [])
    if isinstance(runs, list):
        runs.append(run_doc)
        state["runs"] = runs[-48:]
    state["last_checkin"] = run_doc
    _save_state(state)

    return {
        "ok": True,
        "site_id": sid,
        "summary": summary,
        "throughput": throughput,
        "building_status": {
            "status": building.get("status"),
            "traffic": building.get("traffic"),
            "alert_count": len(building.get("alerts") or []),
            "fdd_alert_count": building.get("fdd_alert_count"),
        },
        "device_poll_health": {
            "summary_sentence": poll_health.get("summary_sentence"),
            "healthy_count": poll_health.get("healthy_count"),
            "offline": (poll_health.get("offline_equipment") or [])[:6],
            "flaky": (poll_health.get("flaky_equipment") or [])[:6],
        },
        "fdd": fdd,
        "tuning_brief": tuning,
        "ops_logs_summary": ops.get("summary"),
        "actions": actions,
        "batch": batch_result,
        "memory": memory_result,
        "auto_tune_enabled": auto_tune,
        "checkin_state_path": str(_state_path()),
    }


def get_checkin_status() -> dict[str, Any]:
    state = _load_state()
    return {"ok": True, **state}
