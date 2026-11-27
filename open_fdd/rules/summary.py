"""Group a rule run's results and explain an all-skipped run (#1661)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

ASSESSED = ("PASS", "FAULT")
_HINTS = {
    "NOT_APPLICABLE_EQUIPMENT_TYPE": "not applicable to the equipment type",
    "SKIPPED_MISSING_ROLES": "missing input roles",
    "SKIPPED_NO_RUN_PROOF": "no run proof (map supply_fan_operating_status / supply_fan_command or a operating_status role)",
    "SKIPPED_EQUIPMENT_OFF": "the equipment was never proven on",
    "NOT_ASSESSED_NO_OCCUPANCY": "no occupancy role or schedule",
    "ERROR": "rule error",
}


def summarize(results: Iterable[Any], *, top_roles: int = 5) -> dict[str, Any]:
    """Counts by status, the most-needed missing roles, and one explanation line.

    ``explanation`` is empty when at least one rule was assessed (PASS or FAULT). When none was, it names the
    reason: no equipment type, the missing roles that would unlock the most rules, no run proof, and so on.
    """
    rows = list(results)
    by_status = Counter(str(r.status) for r in rows)
    types = sorted({str(getattr(r, "equipment_type", "") or "UNKNOWN") for r in rows})
    missing = Counter()
    for r in rows:
        if str(r.status) == "SKIPPED_MISSING_ROLES":
            missing.update(dict.fromkeys(getattr(r, "missing_roles", None) or [], 1))
    assessed = sum(by_status.get(s, 0) for s in ASSESSED)
    reasons: list[str] = []
    if rows and types == ["UNKNOWN"] and by_status.get("NOT_APPLICABLE_EQUIPMENT_TYPE", 0) == len(rows):
        reasons.append(
            "no equipment type: pass equipment_type= (for example 'AHU') or set df.attrs['equipment_type']"
        )
    else:
        for status, hint in _HINTS.items():
            n = by_status.get(status, 0)
            if not n:
                continue
            line = f"{n} {hint}"
            if status == "SKIPPED_MISSING_ROLES" and missing:
                top = ", ".join(f"{role} ({k})" for role, k in missing.most_common(top_roles))
                line += f"; most needed: {top}"
            if status == "NOT_APPLICABLE_EQUIPMENT_TYPE":
                line += f" ({', '.join(types)})"
            reasons.append(line)
    return {
        "total": len(rows),
        "assessed": assessed,
        "all_skipped": bool(rows) and assessed == 0,
        "by_status": dict(sorted(by_status.items())),
        "equipment_types": types,
        "missing_roles": dict(missing.most_common()),
        "reasons": reasons,
        "explanation": "" if assessed or not rows else "no rule was assessed: " + "; ".join(reasons),
    }
