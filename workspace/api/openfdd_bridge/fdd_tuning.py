"""FDD tuning brief — structured recommendations for building agent / sales demos."""

from __future__ import annotations

import os
from typing import Any

from .fdd_results import load_results
from .fdd_runner import run_batch
from .poll_throughput import compute_poll_throughput
from .rule_store import RuleStore

_BOUNDS_KEYS = ("bounds_low", "bounds_high", "bounds_low_rh", "bounds_high_rh")
_MAX_WIDEN = 15.0
_BOUNDS_CUSHION = 2.0


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


def _float_or_none(val: Any) -> float | None:
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _poll_ready(throughput: dict[str, Any]) -> bool:
    keepup = throughput.get("keepup_ratio")
    return throughput.get("status") in {"healthy", "warming"} and (
        keepup is None or float(keepup) >= 0.85
    )


def propose_bounds_patch(
    *,
    run: dict[str, Any],
    rule: dict[str, Any] | None,
    min_flagged_pct: float = 85.0,
) -> dict[str, Any] | None:
    """AI-assisted bounds proposal from fault analytics (human or API applies)."""
    pct = _flagged_pct(run)
    if pct is None or pct < float(min_flagged_pct):
        return None
    analytics = run.get("analytics") if isinstance(run.get("analytics"), dict) else {}
    cfg = (rule or {}).get("config") if isinstance((rule or {}).get("config"), dict) else {}
    if not cfg and not analytics:
        return None

    is_rh = analytics.get("value_unit") == "%RH" or bool(
        cfg.get("bounds_low_rh") is not None or cfg.get("bounds_high_rh") is not None
    )
    low_key = "bounds_low_rh" if is_rh else "bounds_low"
    high_key = "bounds_high_rh" if is_rh else "bounds_high"

    low = _float_or_none(analytics.get(low_key)) or _float_or_none(cfg.get(low_key))
    high = _float_or_none(analytics.get(high_key)) or _float_or_none(cfg.get(high_key))
    min_f = _float_or_none(analytics.get("min_value_fault"))
    max_f = _float_or_none(analytics.get("max_value_fault"))
    avg_f = _float_or_none(analytics.get("avg_value_fault"))
    if low is None or high is None or min_f is None or max_f is None:
        return None

    proposed: dict[str, float] = {}
    rationale: list[str] = []
    unit = analytics.get("value_unit") or ("°F" if not is_rh else "%RH")

    if avg_f is not None and avg_f > high - 0.5 and max_f > high:
        new_high = round(min(max_f + _BOUNDS_CUSHION, high + _MAX_WIDEN), 1)
        if new_high > high:
            proposed[high_key] = new_high
            rationale.append(
                f"fault avg {avg_f}{unit} above high {high}{unit}; widen high toward {new_high}{unit}"
            )
    if avg_f is not None and avg_f < low + 0.5 and min_f < low:
        new_low = round(max(min_f - _BOUNDS_CUSHION, low - _MAX_WIDEN), 1)
        if new_low < low:
            proposed[low_key] = new_low
            rationale.append(
                f"fault avg {avg_f}{unit} below low {low}{unit}; widen low toward {new_low}{unit}"
            )

    if not proposed:
        return None

    rid = str(run.get("rule_id") or (rule or {}).get("id") or "")
    return {
        "rule_id": rid,
        "rule_name": run.get("rule_name") or (rule or {}).get("name"),
        "kind": "bounds_widen",
        "flagged_pct": pct,
        "current_bounds": {k: cfg[k] for k in _BOUNDS_KEYS if k in cfg},
        "proposed_config": proposed,
        "merged_config": {**cfg, **proposed},
        "rationale": "; ".join(rationale),
        "analytics": analytics,
    }


def collect_tuning_patches(
    *,
    site_id: str,
    rule_ids: list[str] | None = None,
    min_flagged_pct: float = 70.0,
) -> list[dict[str, Any]]:
    """Collect AI-proposed config patches for elevated flag-rate rules."""
    store = RuleStore()
    rules_by_id = {str(r.get("id")): r for r in store.list_rules() if isinstance(r, dict)}
    allow = {str(x).strip() for x in (rule_ids or []) if str(x).strip()} or None

    doc = load_results()
    runs = [r for r in doc.get("runs", []) if isinstance(r, dict)]
    site_runs = [r for r in runs if str(r.get("site_id") or "") in {"", site_id}]

    patches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for run in site_runs:
        if run.get("status") == "error":
            continue
        rid = str(run.get("rule_id") or "")
        if not rid or rid in seen:
            continue
        if allow is not None and rid not in allow:
            continue
        patch = propose_bounds_patch(
            run=run,
            rule=rules_by_id.get(rid),
            min_flagged_pct=min_flagged_pct,
        )
        if patch:
            patches.append(patch)
            seen.add(rid)
    return patches


def apply_tuning_patches(
    *,
    site_id: str,
    apply: bool = False,
    rule_ids: list[str] | None = None,
    run_fdd_batch: bool = False,
    saved_by: str = "building-agent",
) -> dict[str, Any]:
    """Dry-run or apply AI-proposed bounds patches (poll-gated)."""
    throughput = compute_poll_throughput(window_minutes=60)
    poll_ready = _poll_ready(throughput)
    auto_tune_env = os.environ.get("OFDD_AGENT_AUTO_TUNE", "").strip().lower() in {"1", "true", "yes"}

    patches = collect_tuning_patches(
        site_id=site_id,
        rule_ids=rule_ids,
        min_flagged_pct=85.0,
    )
    if not poll_ready:
        return {
            "ok": True,
            "site_id": site_id,
            "dry_run": not apply,
            "applied": False,
            "poll_ready_for_tuning": False,
            "throughput_status": throughput.get("status"),
            "keepup_ratio": throughput.get("keepup_ratio"),
            "patches": patches,
            "message": "Poll keepup below 85% — proposals only, no apply.",
            "auto_tune_env": auto_tune_env,
        }

    if not apply:
        return {
            "ok": True,
            "site_id": site_id,
            "dry_run": True,
            "applied": False,
            "poll_ready_for_tuning": True,
            "patches": patches,
            "message": f"{len(patches)} patch(es) ready — POST with apply=true to save.",
            "auto_tune_env": auto_tune_env,
        }

    store = RuleStore()
    applied: list[dict[str, Any]] = []
    for patch in patches:
        rid = str(patch.get("rule_id") or "")
        rule = store.get(rid)
        if not rule:
            continue
        merged = dict(rule)
        merged["config"] = patch.get("merged_config") or {**(rule.get("config") or {}), **(patch.get("proposed_config") or {})}
        entry = store.upsert(merged, saved_by=saved_by)
        applied.append(
            {
                "rule_id": rid,
                "rule_name": entry.get("name"),
                "proposed_config": patch.get("proposed_config"),
                "rationale": patch.get("rationale"),
            }
        )

    batch_result = None
    if run_fdd_batch and applied:
        try:
            batch_result = run_batch(limit=500)
        except Exception as exc:  # noqa: BLE001
            batch_result = {"ok": False, "error": str(exc)[:500]}

    return {
        "ok": True,
        "site_id": site_id,
        "dry_run": False,
        "applied": bool(applied),
        "poll_ready_for_tuning": True,
        "patches_proposed": len(patches),
        "patches_applied": applied,
        "batch": batch_result,
        "auto_tune_env": auto_tune_env,
        "message": f"Applied {len(applied)} bounds patch(es).",
    }


def build_tuning_brief(
    *,
    site_id: str,
    window_minutes: int = 60,
    include_patches: bool = True,
) -> dict[str, Any]:
    """Human + agent readable FDD tuning queue (poll-gated)."""
    throughput = compute_poll_throughput(window_minutes=window_minutes)
    poll_ready = _poll_ready(throughput)
    keepup = throughput.get("keepup_ratio")

    doc = load_results()
    runs = [r for r in doc.get("runs", []) if isinstance(r, dict)]
    site_runs = [r for r in runs if str(r.get("site_id") or "") in {"", site_id}]
    rules_by_id = {
        str(r.get("id")): r
        for r in RuleStore().list_rules()
        if isinstance(r, dict)
    }

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
        patch = (
            propose_bounds_patch(
                run=run,
                rule=rules_by_id.get(rid),
                min_flagged_pct=85.0,
            )
            if include_patches and poll_ready and pct is not None and pct >= 85.0
            else None
        )
        if pct >= 85.0:
            rec: dict[str, Any] = {
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
                "suggested_tool": "building.apply_tuning (dry_run) then apply=true",
            }
            if patch:
                rec["proposed_patch"] = patch
            recommendations.append(rec)
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

    patches = collect_tuning_patches(site_id=site_id) if include_patches and poll_ready else []

    parts = [
        f"Poll {throughput.get('status')} keepup={keepup}",
        f"{len([r for r in recommendations if r['kind'] == 'rule_error'])} rule error(s)",
        f"{len([r for r in recommendations if r['kind'] == 'threshold_review'])} threshold review(s)",
    ]
    if patches:
        parts.append(f"{len(patches)} AI bounds patch(es) ready")
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
        "patches": patches[:12],
        "summary_sentence": "; ".join(parts),
        "methodology": (
            "Errors fixed first. Threshold tuning only when BACnet poll keepup >= 85%. "
            "GET tuning-brief for AI proposals; POST apply-tuning with apply=true to save. "
            "Set OFDD_AGENT_AUTO_TUNE=1 for unattended cron apply (future)."
        ),
    }
