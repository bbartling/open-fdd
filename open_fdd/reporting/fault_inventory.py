"""FAULT inventory export — orphans / suppressed terminal faults (BUG-023)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from open_fdd.reporting.scope import equipment_system
from open_fdd.reporting.models import CandidateDetection, EngineeringFinding


def build_fault_inventory(
    candidates: list[CandidateDetection] | list[dict[str, Any]],
    findings: list[EngineeringFinding],
    *,
    suppressed: list[dict[str, Any]] | None = None,
    statuses: set[str] | None = None,
) -> dict[str, Any]:
    """List FAULT (or configured) detections with in_priority + suppressed_reason."""
    want = {s.upper() for s in (statuses or {"FAULT"})}
    priority_keys: set[str] = set()
    for f in findings:
        if not f.include_in_report:
            continue
        keys = list(f.candidate_keys or [])
        if keys:
            priority_keys.update(keys)
        else:
            # Legacy / pin edge case: only then fall back to equipment×rule pairs
            for eid in f.equipment_ids or []:
                for rid in f.rule_ids or []:
                    priority_keys.add(f"{eid}|{rid}")

    suppress_by_key: dict[str, str] = {}
    for row in suppressed or []:
        key = str(row.get("candidate_key") or "")
        reasons = row.get("reasons") or []
        reason = "; ".join(str(r) for r in reasons) if reasons else str(row.get("classification") or "suppressed")
        if key:
            for part in key.split(","):
                part = part.strip()
                if part:
                    suppress_by_key[part] = reason

    rows: list[dict[str, Any]] = []
    for raw in candidates:
        if isinstance(raw, CandidateDetection):
            c = raw
            status = (c.status or "").upper()
            eid = c.equipment_id
            rid = c.rule_id
            et = c.equipment_type
            hours = c.fault_hours
            samples = c.sample_count
            key = c.key
        else:
            status = str(raw.get("status") or "").upper()
            eid = str(raw.get("equipment_id") or "")
            rid = str(raw.get("rule_id") or "")
            et = str(raw.get("equipment_type") or "")
            hours = raw.get("fault_hours")
            samples = int(raw.get("sample_count") or 0)
            key = str(raw.get("key") or f"{eid}|{rid}")
        if status and status not in want:
            continue
        in_priority = key in priority_keys
        suppressed_reason = None
        if not in_priority:
            suppressed_reason = suppress_by_key.get(key) or "not_in_priority_pack"
        sys = equipment_system(et, rid)
        prefix = _equip_prefix(eid)
        rows.append(
            {
                "equipment": eid,
                "equipment_prefix": prefix,
                "system": sys,
                "rule_id": rid,
                "status": status or "FAULT",
                "fault_samples": samples,
                "fault_hours": hours,
                "in_priority": in_priority,
                "suppressed_reason": suppressed_reason,
                "candidate_key": key,
            }
        )

    by_rule: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "fault_hours": 0.0, "in_priority": 0})
    by_prefix: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "fault_hours": 0.0, "in_priority": 0})
    for r in rows:
        br = by_rule[r["rule_id"]]
        br["count"] += 1
        br["fault_hours"] += float(r["fault_hours"] or 0)
        br["in_priority"] += 1 if r["in_priority"] else 0
        bp = by_prefix[r["equipment_prefix"]]
        bp["count"] += 1
        bp["fault_hours"] += float(r["fault_hours"] or 0)
        bp["in_priority"] += 1 if r["in_priority"] else 0

    orphans = [r for r in rows if not r["in_priority"]]
    orphans_sorted = sorted(orphans, key=lambda x: -float(x["fault_hours"] or 0))
    n_priority_findings = sum(1 for f in findings if f.include_in_report)
    n_candidates_in_priority = sum(1 for r in rows if r["in_priority"])

    return {
        "rows": rows,
        "orphans": orphans_sorted,
        "rollup_by_rule_id": dict(by_rule),
        "rollup_by_equipment_prefix": dict(by_prefix),
        "n_faults": len(rows),
        # Candidate FAULT rows covered by a priority finding (may be >> findings count)
        "n_candidates_in_priority": n_candidates_in_priority,
        # Body findings count — what agents usually mean by "in priority" (BUG-040)
        "n_priority_findings": n_priority_findings,
        # Back-compat: prefer findings count for n_in_priority (was candidate-row count)
        "n_in_priority": n_priority_findings,
        "n_orphans": len(orphans),
    }


def _equip_prefix(eid: str) -> str:
    s = (eid or "").upper()
    if not s:
        return "OTHER"
    # VAV_22 → VAV; AHU-1 → AHU; CHW_PLANT → CHW
    for sep in ("_", "-", " "):
        if sep in s:
            return s.split(sep, 1)[0]
    # strip trailing digits
    i = len(s)
    while i > 0 and s[i - 1].isdigit():
        i -= 1
    return s[:i] if i else s
