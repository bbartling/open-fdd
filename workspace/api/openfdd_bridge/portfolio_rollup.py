"""Single JSON snapshot for central portfolio collectors (no pandas on edge)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .building_agent import get_checkin_status
from .building_status import collect_status
from .fdd_results import load_results
from .poll_throughput import compute_poll_throughput
from .runtime_metrics import load_runtime_metrics
from .site_defaults import ensure_default_site

try:
    from bacnet_toolshed.override_registry import (
        load_registry,
        operator_override_priority,
        override_status,
    )
except ImportError:

    def load_registry():  # type: ignore[misc]
        return {"devices": {}}

    def operator_override_priority() -> int:
        return 8

    def override_status() -> dict[str, Any]:
        return {"ok": True, "operator_override_points": 0, "total_override_points": 0}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fault_counts_from_status(status: dict[str, Any]) -> dict[str, Any]:
    active_by_code: Counter[str] = Counter()
    active_by_family: Counter[str] = Counter()
    for alert in status.get("alerts") or []:
        if not isinstance(alert, dict):
            continue
        code = str(alert.get("code") or "").strip().upper()
        if code:
            active_by_code[code] += 1
        family = str(alert.get("equipment_family") or "").strip().upper()
        if family:
            active_by_family[family] += 1
    return {
        "active_count": sum(active_by_code.values()),
        "active_by_code": dict(sorted(active_by_code.items())),
        "active_by_family": dict(sorted(active_by_family.items())),
    }


def _fdd_batch_summary() -> dict[str, Any]:
    doc = load_results()
    flagged_by_code: Counter[str] = Counter()
    error_count = 0
    flagged_runs = 0
    for run in doc.get("runs") or []:
        if not isinstance(run, dict):
            continue
        if run.get("status") == "error":
            error_count += 1
            continue
        flagged = int(run.get("flagged") or 0)
        if flagged <= 0:
            continue
        flagged_runs += 1
        code = str(run.get("fault_code") or "").strip().upper()
        if code:
            flagged_by_code[code] += flagged
    return {
        "generated_at": doc.get("generated_at"),
        "flagged_runs": flagged_runs,
        "error_runs": error_count,
        "flagged_samples_by_code": dict(sorted(flagged_by_code.items())),
    }


def _operator_overrides_detail() -> dict[str, Any]:
    status = override_status()
    op_pri = operator_override_priority()
    data = load_registry()
    points: list[dict[str, Any]] = []
    by_device: Counter[str] = Counter()
    for dev in sorted((data.get("devices") or {}).values(), key=lambda d: int(d.get("device_instance") or 0)):
        if not isinstance(dev, dict):
            continue
        inst = int(dev.get("device_instance") or 0)
        addr = str(dev.get("device_address") or "")
        for pt in dev.get("points_with_overrides") or []:
            if not isinstance(pt, dict):
                continue
            oid = str(pt.get("object_identifier") or "")
            name = str(pt.get("object_name") or oid)
            for slot in pt.get("overrides") or []:
                if not isinstance(slot, dict):
                    continue
                pl = int(slot.get("priority_level") or 0)
                if pl != op_pri:
                    continue
                val = slot.get("value")
                key = f"dev{inst}"
                by_device[key] += 1
                points.append(
                    {
                        "device_instance": inst,
                        "device_address": addr,
                        "object_identifier": oid,
                        "object_name": name,
                        "priority_level": pl,
                        "value": val,
                    }
                )
    return {
        "operator_priority": op_pri,
        "operator_override_points": int(status.get("operator_override_points") or len(points)),
        "total_override_points": int(status.get("total_override_points") or 0),
        "by_device": dict(sorted(by_device.items())),
        "points": points,
        "last_scan_at": str(data.get("last_scan_at") or ""),
    }


def _runtime_for_site(site_id: str) -> dict[str, Any]:
    doc = load_runtime_metrics()
    sites = doc.get("sites") if isinstance(doc.get("sites"), dict) else {}
    bucket = sites.get(site_id) if isinstance(sites, dict) else {}
    if not isinstance(bucket, dict):
        return {}
    out: dict[str, Any] = {}
    for equipment_id, metrics in bucket.items():
        if not isinstance(metrics, dict):
            continue
        out[str(equipment_id)] = {
            k: metrics.get(k)
            for k in (
                "equipment_id",
                "equipment_name",
                "fan_run_hours",
                "system_run_hours",
                "unoccupied_fan_hours",
                "unoccupied_system_hours",
                "window_start",
                "window_end",
                "recorded_at",
            )
            if metrics.get(k) is not None
        }
    return out


def build_portfolio_rollup(*, site_id: str | None = None) -> dict[str, Any]:
    """Aggregate edge telemetry for central portfolio analytics."""
    sid = str(site_id or ensure_default_site() or "default").strip()
    status = collect_status()
    faults = _fault_counts_from_status(status)
    overrides = _operator_overrides_detail()
    throughput = compute_poll_throughput(window_minutes=60)
    agent_state = get_checkin_status()
    last_checkin = agent_state.get("last_checkin") if isinstance(agent_state.get("last_checkin"), dict) else {}

    return {
        "ok": True,
        "schema_version": 1,
        "generated_at": _now_iso(),
        "site_id": sid,
        "building": {
            "status": status.get("status"),
            "traffic": status.get("traffic"),
            "alert_count": len(status.get("alerts") or []),
            "fdd_alert_count": status.get("fdd_alert_count"),
            "check_engine": status.get("status") != "ok",
        },
        "faults": faults,
        "fdd_batch": _fdd_batch_summary(),
        "runtime_metrics": _runtime_for_site(sid),
        "overrides": overrides,
        "poll": {
            "summary_sentence": throughput.get("summary_sentence"),
            "points_polled": throughput.get("points_polled"),
            "ingest_rows_per_min": throughput.get("ingest_rows_per_min"),
            "cycle_model": throughput.get("cycle_model"),
        },
        "agent": {
            "last_checkin_at": last_checkin.get("finished_at") or last_checkin.get("started_at"),
            "last_checkin_ok": last_checkin.get("ok"),
            "last_summary": last_checkin.get("summary") if isinstance(last_checkin.get("summary"), dict) else {},
        },
    }
