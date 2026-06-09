"""Append-only CSV history for central portfolio analytics (pandas optional at read time)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def portfolio_data_dir(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[1]
    path = base / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _append_rows(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    write_header = not path.is_file() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return len(rows)


def _day_key(iso_ts: str) -> str:
    return str(iso_ts or "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")


CHECKIN_FIELDS = [
    "collected_at",
    "site_id",
    "site_name",
    "base_url",
    "traffic",
    "status",
    "alert_count",
    "fdd_alert_count",
    "operator_overrides",
    "checkin_ok",
    "poll_summary",
    "error",
]

RUN_HOURS_FIELDS = [
    "collected_at",
    "day",
    "site_id",
    "equipment_id",
    "equipment_name",
    "fan_run_hours",
    "system_run_hours",
    "unoccupied_fan_hours",
    "unoccupied_system_hours",
]

FAULTS_FIELDS = [
    "collected_at",
    "day",
    "site_id",
    "fault_code",
    "active_count",
    "flagged_samples",
]

OVERRIDES_FIELDS = [
    "collected_at",
    "day",
    "site_id",
    "device_instance",
    "object_identifier",
    "object_name",
    "priority_level",
    "value",
]


def rows_from_rollup(
    rollup: dict[str, Any],
    *,
    site_name: str,
    base_url: str,
    collected_at: str | None = None,
    error: str = "",
) -> dict[str, list[dict[str, Any]]]:
    ts = collected_at or datetime.now(timezone.utc).isoformat()
    day = _day_key(ts)
    site_id = str(rollup.get("site_id") or "unknown")
    building = rollup.get("building") if isinstance(rollup.get("building"), dict) else {}
    faults = rollup.get("faults") if isinstance(rollup.get("faults"), dict) else {}
    fdd = rollup.get("fdd_batch") if isinstance(rollup.get("fdd_batch"), dict) else {}
    overrides = rollup.get("overrides") if isinstance(rollup.get("overrides"), dict) else {}
    agent = rollup.get("agent") if isinstance(rollup.get("agent"), dict) else {}
    poll = rollup.get("poll") if isinstance(rollup.get("poll"), dict) else {}

    checkin_row = {
        "collected_at": ts,
        "site_id": site_id,
        "site_name": site_name,
        "base_url": base_url,
        "traffic": building.get("traffic"),
        "status": building.get("status"),
        "alert_count": building.get("alert_count"),
        "fdd_alert_count": building.get("fdd_alert_count"),
        "operator_overrides": overrides.get("operator_override_points"),
        "checkin_ok": agent.get("last_checkin_ok"),
        "poll_summary": poll.get("summary_sentence"),
        "error": error,
    }

    run_rows: list[dict[str, Any]] = []
    metrics = rollup.get("runtime_metrics") if isinstance(rollup.get("runtime_metrics"), dict) else {}
    for equipment_id, m in metrics.items():
        if not isinstance(m, dict):
            continue
        run_rows.append(
            {
                "collected_at": ts,
                "day": day,
                "site_id": site_id,
                "equipment_id": equipment_id,
                "equipment_name": m.get("equipment_name") or equipment_id,
                "fan_run_hours": m.get("fan_run_hours"),
                "system_run_hours": m.get("system_run_hours"),
                "unoccupied_fan_hours": m.get("unoccupied_fan_hours"),
                "unoccupied_system_hours": m.get("unoccupied_system_hours"),
            }
        )

    active_by_code = faults.get("active_by_code") if isinstance(faults.get("active_by_code"), dict) else {}
    flagged_by_code = (
        fdd.get("flagged_samples_by_code") if isinstance(fdd.get("flagged_samples_by_code"), dict) else {}
    )
    codes = sorted(set(active_by_code) | set(flagged_by_code))
    fault_rows = [
        {
            "collected_at": ts,
            "day": day,
            "site_id": site_id,
            "fault_code": code,
            "active_count": int(active_by_code.get(code) or 0),
            "flagged_samples": int(flagged_by_code.get(code) or 0),
        }
        for code in codes
    ]

    override_rows: list[dict[str, Any]] = []
    for pt in overrides.get("points") or []:
        if not isinstance(pt, dict):
            continue
        override_rows.append(
            {
                "collected_at": ts,
                "day": day,
                "site_id": site_id,
                "device_instance": pt.get("device_instance"),
                "object_identifier": pt.get("object_identifier"),
                "object_name": pt.get("object_name"),
                "priority_level": pt.get("priority_level"),
                "value": pt.get("value"),
            }
        )

    return {
        "checkins": [checkin_row],
        "run_hours": run_rows,
        "faults": fault_rows,
        "overrides": override_rows,
    }


def append_rollup(
    rollup: dict[str, Any],
    *,
    site_name: str,
    base_url: str,
    data_dir: Path | None = None,
    error: str = "",
) -> dict[str, int]:
    root = portfolio_data_dir(data_dir)
    rows = rows_from_rollup(rollup, site_name=site_name, base_url=base_url, error=error)
    return {
        "checkins": _append_rows(root / "checkins.csv", CHECKIN_FIELDS, rows["checkins"]),
        "run_hours": _append_rows(root / "run_hours_daily.csv", RUN_HOURS_FIELDS, rows["run_hours"]),
        "faults": _append_rows(root / "faults_daily.csv", FAULTS_FIELDS, rows["faults"]),
        "overrides": _append_rows(root / "overrides_daily.csv", OVERRIDES_FIELDS, rows["overrides"]),
    }


def save_rollup_json(rollup: dict[str, Any], *, site_id: str, data_dir: Path | None = None) -> Path:
    root = portfolio_data_dir(data_dir)
    latest = root / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    path = latest / f"{site_id}.json"
    path.write_text(json.dumps(rollup, indent=2), encoding="utf-8")
    return path
