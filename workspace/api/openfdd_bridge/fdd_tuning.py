"""FDD tuning brief — structured recommendations for building agent / sales demos."""

from __future__ import annotations

from typing import Any

from .fdd_results import load_results
from .poll_throughput import compute_poll_throughput


def _flagged_pct(run: dict[str, Any]) -> float | None:
    rows = int(run.get("rows") or 0)
    flagged = int(run.get("flagged") or 0)
    if rows <= 0:
        return None
    return round(100.0 * flagged / rows, 1)


def _error_hint(error: str, rule_id: str) -> str:
    err = (error or "").strip().lower()
    if "df" in err and "not defined" in err:
        return "Bridge script-runner bug (fixed in 3.0.9) — redeploy and re-run batch."
    if "timestamp column required" in err:
        return "Bind historian columns or widen lookback; script needs feather timestamps."
    if "name " in err and "not defined" in err:
        return "Rule Python references undefined variable — open Rule Lab source and fix."
    if "arrow" in err or "pyarrow" in err:
        return "Arrow rule failed — verify column_map and feather column names."
    return f"Inspect rule '{rule_id}' in Rule Lab; re-run POST /api/rules/batch after fix."


def build_tuning_brief(
    *,
    site_id: str,
    window_minutes: int = 60,
) -> dict[str, Any]:
    """Human + agent readable FDD tuning queue (poll-gated)."""
    throughput = compute_poll_throughput(window_minutes=window_minutes)
    keepup = throughput.get("keepup_ratio")
    poll_ready = (
        throughput.get("status") in {"healthy", "warming"}
        and (keepup is None or float(keepup) >= 0.85)
    )

    doc = load_results()
    runs = [r for r in doc.get("runs", []) if isinstance(r, dict)]
    site_runs = [r for r in runs if str(r.get("site_id") or "") in {"", site_id}]

    recommendations: list[dict[str, Any]] = []
    for run in site_runs:
        if run.get("status") == "error":
            rid = str(run.get("rule_id") or "")
            err = str(run.get("error") or "")
            recommendations.append(
                {
                    "priority": "critical",
                    "kind": "rule_error",
                    "rule_id": rid,
                    "rule_name": run.get("rule_name"),
                    "fault_code": run.get("fault_code"),
                    "detail": err[:500],
                    "hint": _error_hint(err, rid),
                    "poll_ready": poll_ready,
                    "suggested_tool": "rules.save (fix code) + rules.run_batch",
                }
            )
            continue
        pct = _flagged_pct(run)
        if pct is None:
            continue
        flagged_n = int(run.get("flagged") or 0)
        rows = int(run.get("rows") or 0)
        analytics = run.get("analytics") if isinstance(run.get("analytics"), dict) else {}
        rid = str(run.get("rule_id") or "")
        rname = str(run.get("rule_name") or rid)
        if pct >= 85.0:
            recommendations.append(
                {
                    "priority": "high",
                    "kind": "threshold_review",
                    "rule_id": rid,
                    "rule_name": rname,
                    "fault_code": run.get("fault_code"),
                    "flagged_pct": pct,
                    "flagged": flagged_n,
                    "rows": rows,
                    "detail": f"{flagged_n}/{rows} samples flagged ({pct}%)",
                    "hint": "Likely bounds too tight or wrong bind — review config.bounds_low/high",
                    "analytics": analytics,
                    "poll_ready": poll_ready,
                    "suggested_tool": "rules.save (config) + rules.run_batch",
                }
            )
        elif pct >= 40.0 and flagged_n >= 3:
            recommendations.append(
                {
                    "priority": "medium",
                    "kind": "watch",
                    "rule_id": rid,
                    "rule_name": rname,
                    "fault_code": run.get("fault_code"),
                    "flagged_pct": pct,
                    "flagged": flagged_n,
                    "rows": rows,
                    "detail": f"{flagged_n}/{rows} flagged ({pct}%) — monitor before tuning",
                    "poll_ready": poll_ready,
                }
            )

    recommendations.sort(
        key=lambda r: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(r.get("priority")), 9)
    )

    parts = [
        f"Poll {throughput.get('status')} keepup={keepup}",
        f"{len([r for r in recommendations if r['kind'] == 'rule_error'])} rule error(s)",
        f"{len([r for r in recommendations if r['kind'] == 'threshold_review'])} threshold review(s)",
    ]
    if not poll_ready:
        parts.append("defer threshold tuning until keepup_ratio >= 0.85")

    return {
        "ok": True,
        "site_id": site_id,
        "poll_ready_for_tuning": poll_ready,
        "throughput_status": throughput.get("status"),
        "keepup_ratio": keepup,
        "enabled_points": throughput.get("enabled_points"),
        "recommendations": recommendations[:20],
        "summary_sentence": "; ".join(parts),
        "methodology": (
            "Errors fixed first. Threshold tuning only when BACnet poll keepup >= 85%. "
            "Human approves rules.save config changes; set OFDD_AGENT_AUTO_TUNE=1 for future auto-apply."
        ),
    }
