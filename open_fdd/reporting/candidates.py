"""Build CandidateDetection lists from RuleResult or checklist JSON."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from open_fdd.reporting.models import CandidateDetection
from open_fdd.reporting.rule_meta import rule_label
from open_fdd.rules.base import RuleResult


def candidates_from_rule_results(
    results: list[RuleResult],
    *,
    building: str,
    analysis_period: str = "",
) -> list[CandidateDetection]:
    out: list[CandidateDetection] = []
    for r in results:
        if r.status != "FAULT":
            continue
        out.append(
            CandidateDetection(
                building=building or r.building_id or "",
                equipment_id=r.equipment_id,
                equipment_type=r.equipment_type or "UNKNOWN",
                rule_id=r.rule_id,
                rule_label=rule_label(r.rule_id),
                status=r.status,
                fault_hours=r.fault_hours,
                fault_pct=r.fault_pct,
                sample_count=r.sample_count,
                missing_roles=list(r.missing_roles or []),
                notes=r.notes or "",
                analysis_period=analysis_period,
            )
        )
    return out


def candidates_from_checklist_json(
    data: dict[str, Any] | Path | str,
    *,
    building: str | None = None,
) -> tuple[list[CandidateDetection], dict[str, Any]]:
    """Load dump-checklist JSON (controls_service_checklist output) into candidates + context."""
    if isinstance(data, (str, Path)):
        payload = json.loads(Path(data).read_text(encoding="utf-8"))
    else:
        payload = data

    summary = payload.get("summary") or {}
    bname = building or summary.get("building_name") or summary.get("building") or "BUILDING"
    span = summary.get("span_hours")
    period = f"~{span:.0f} h window" if isinstance(span, (int, float)) else ""

    # Telemetry spots from unusual_faults rows
    spot_by_key: dict[str, dict[str, Any]] = {}
    unusual = payload.get("unusual_faults") or {}
    for row in unusual.get("rows") or []:
        eid = row.get("equipment_id")
        rid = row.get("rule_id")
        if not eid or not rid:
            continue
        spot_by_key[f"{eid}|{rid}"] = _parse_spot(row.get("telemetry_spot") or row.get("spot") or "")

    faults = (payload.get("fdd") or {}).get("all_faults") or []
    cands: list[CandidateDetection] = []
    for row in faults:
        eid = str(row.get("equipment_id") or "")
        rid = str(row.get("rule_id") or "")
        if not eid or not rid:
            continue
        missing = row.get("missing_roles") or ""
        missing_list = [m.strip() for m in str(missing).split(",") if m.strip()]
        key = f"{eid}|{rid}"
        cands.append(
            CandidateDetection(
                building=bname,
                equipment_id=eid,
                equipment_type=str(row.get("equipment_type") or "UNKNOWN"),
                rule_id=rid,
                rule_label=rule_label(rid, fallback=str(row.get("label") or "")),
                status="FAULT",
                fault_hours=_f(row.get("fault_hours")),
                fault_pct=_f(row.get("fault_pct")),
                missing_roles=missing_list,
                notes=str(row.get("notes") or ""),
                ecm_flag=row.get("ecm_flag"),
                analysis_period=period,
                telemetry_spot=spot_by_key.get(key, {}),
            )
        )

    # Promote fan-off anomalies as synthetic sensor findings
    for fo in payload.get("fan_off_anomalies") or []:
        eid = str(fo.get("equipment_id") or "")
        if not eid:
            continue
        cands.append(
            CandidateDetection(
                building=bname,
                equipment_id=eid,
                equipment_type="AHU",
                rule_id="FAN-OFF-STATIC",
                rule_label="Duct static with fan OFF",
                status="FAULT",
                fault_hours=None,
                fault_pct=None,
                notes=str(fo.get("note") or ""),
                ecm_flag=fo.get("ecm_flag"),
                analysis_period=period,
                extras={"fan_off_anomaly": fo},
            )
        )

    context = {
        "summary": summary,
        "comfort": payload.get("comfort") or {},
        "fan_off_anomalies": payload.get("fan_off_anomalies") or [],
        "unusual_faults": unusual,
        "gaps": payload.get("gaps") or {},
        "building": bname,
        "analysis_period": period,
    }
    return cands, context


def _parse_spot(text: str) -> dict[str, Any]:
    """Parse 'damper=0.0, zone-airflow=201.668, …' into a dict."""
    out: dict[str, Any] = {}
    if not text or not isinstance(text, str):
        return out
    for part in text.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        try:
            out[k] = float(v)
        except ValueError:
            out[k] = v
    return out


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def comfort_index(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = (context.get("comfort") or {}).get("rows") or []
    return {str(r.get("equipment_id")): r for r in rows if r.get("equipment_id")}


def fan_off_index(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(r.get("equipment_id")): r
        for r in (context.get("fan_off_anomalies") or [])
        if r.get("equipment_id")
    }


def peer_fault_counts(candidates: list[CandidateDetection]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in candidates:
        counts[c.rule_id] = counts.get(c.rule_id, 0) + 1
    return counts


def vav_fleet_size(candidates: list[CandidateDetection], context: dict[str, Any]) -> int:
    comfort_n = (context.get("comfort") or {}).get("n_vav")
    if isinstance(comfort_n, int) and comfort_n > 0:
        return comfort_n
    ids = {c.equipment_id for c in candidates if "VAV" in (c.equipment_type or "").upper() or c.equipment_id.upper().startswith("VAV")}
    return max(len(ids), 1)
