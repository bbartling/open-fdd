"""Deterministic AFDD tuning assistant report (no auto-hidden param changes)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.reports import results_summary_table
from app.rules.base import RuleResult


def _status_counts(results: list[RuleResult]) -> dict[str, int]:
    summary = results_summary_table(results)
    if summary.empty:
        return {}
    return {str(k): int(v) for k, v in summary["status"].value_counts().to_dict().items()}


def build_tuning_assistant_report(
    *,
    baseline: list[RuleResult] | None = None,
    tuned: list[RuleResult] | None = None,
    params: dict[str, dict[str, Any]] | None = None,
    has_web_weather: bool = False,
    gap_report: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compare baseline vs tuned runs and suggest inspection / tuning candidates."""
    tuned = tuned or []
    baseline = baseline or []
    use = tuned or baseline
    summary = results_summary_table(use)
    base_counts = _status_counts(baseline) if baseline else {}
    tuned_counts = _status_counts(tuned) if tuned else _status_counts(use)

    top_rules: list[dict[str, Any]] = []
    top_equip: list[dict[str, Any]] = []
    if not summary.empty and "fault_hours" in summary.columns:
        faults = summary[summary["status"] == "FAULT"].copy()
        if not faults.empty:
            by_rule = (
                faults.groupby("rule_id", as_index=False)["fault_hours"]
                .sum()
                .sort_values("fault_hours", ascending=False)
                .head(10)
            )
            top_rules = by_rule.to_dict(orient="records")
            by_eq = (
                faults.groupby("equipment_id", as_index=False)["fault_hours"]
                .sum()
                .sort_values("fault_hours", ascending=False)
                .head(10)
            )
            top_equip = by_eq.to_dict(orient="records")

    stale_flat = 0
    if not summary.empty:
        stale_flat = int(
            (
                (summary["status"] == "FAULT")
                & summary["rule_id"].isin(["SV-STALE", "SV-FLATLINE"])
            ).sum()
        )
    fault_n = int((summary["status"] == "FAULT").sum()) if not summary.empty else 0
    stale_warning = bool(fault_n and stale_flat / max(fault_n, 1) >= 0.35)

    missing_impact = 0
    if gap_report is not None and not gap_report.empty and "skipped_rule_count" in gap_report.columns:
        missing_impact = int(gap_report["skipped_rule_count"].sum())
    elif not summary.empty:
        missing_impact = int((summary["status"] == "SKIPPED_MISSING_ROLES").sum())

    recommended_plots = [
        "RCx: zone_temps",
        "RCx: ahu_dats",
        "RCx: duct_static_box (fan on)",
        "RCx: hw_reset_scatter / chw_reset_scatter vs web OAT",
        "Plots tab: top FAULT rules by device",
        "Analytics: mech_cooling_oat_bins",
    ]
    if stale_warning:
        recommended_plots.insert(0, "Plots: SV-STALE / SV-FLATLINE on top equipment")

    suggested: list[dict[str, Any]] = []
    for rid in ("SV-FLATLINE", "SV-STALE", "VAV-1", "VAV-7", "ECON-3", "OAT-METEO", "PID-HUNT-1"):
        if not summary.empty and ((summary["rule_id"] == rid) & (summary["status"] == "FAULT")).any():
            suggested.append(
                {
                    "rule_id": rid,
                    "reason": "Has FAULT rows — review confirm_min / thresholds before accepting",
                    "action": "inspect_then_tune",
                }
            )

    delta: dict[str, Any] = {}
    if base_counts and tuned_counts:
        keys = sorted(set(base_counts) | set(tuned_counts))
        delta = {k: int(tuned_counts.get(k, 0) - base_counts.get(k, 0)) for k in keys}

    return {
        "baseline_status_counts": base_counts,
        "tuned_status_counts": tuned_counts,
        "status_delta_tuned_minus_baseline": delta,
        "top_fault_rules_by_hours": top_rules,
        "top_fault_equipment_by_hours": top_equip,
        "stale_flatline_fault_count": stale_flat,
        "stale_flatline_dominance_warning": stale_warning,
        "missing_role_skip_impact": missing_impact,
        "web_weather_used": bool(has_web_weather),
        "active_params": params or {},
        "recommended_plots": recommended_plots,
        "suggested_tuning_candidates": suggested,
        "notes": (
            "Suggestions only — no parameters were auto-changed. "
            "Export fault_settings.json after manual review."
        ),
    }
