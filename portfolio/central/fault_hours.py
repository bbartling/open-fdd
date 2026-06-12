"""Fault-hour analytics from portfolio rollup / validation data."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def fault_summary_from_validation(validation: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract FDD alerts grouped by equipment from a validation result."""
    checks = validation.get("checks") or {}
    faults_body = ((checks.get("faults_status") or {}).get("body") or {})
    rows: list[dict[str, Any]] = []
    for fam in faults_body.get("families") or []:
        label = str(fam.get("label") or fam.get("family") or "")
        for alert in fam.get("faults") or []:
            if not isinstance(alert, dict):
                continue
            ctx = alert.get("model_context") or {}
            eq = ctx.get("equipment") if isinstance(ctx.get("equipment"), dict) else {}
            eq_name = next(
                (
                    s
                    for s in (
                        str(alert.get("equipment_name") or "").strip(),
                        str(eq.get("name") or "").strip(),
                        label,
                    )
                    if s
                ),
                "Unknown equipment",
            )
            rows.append(
                {
                    "site_id": validation.get("site_id"),
                    "equipment": eq_name,
                    "equipment_type": str(eq.get("type") or alert.get("equipment_family") or ""),
                    "code": str(alert.get("code") or ""),
                    "title": str(alert.get("title") or ""),
                    "severity": str(alert.get("severity") or "warning"),
                    "rule_id": str(alert.get("rule_id") or ctx.get("rule_id") or ""),
                }
            )
    return rows


def aggregate_fault_hours(
    rollups: list[dict[str, Any]],
    *,
    hours_per_sample: float = 1.0,
) -> list[dict[str, Any]]:
    """Estimate elapsed fault hours from portfolio rollup fault counters."""
    totals: dict[tuple[str, str, str], float] = defaultdict(float)
    for rollup in rollups:
        site_id = str(rollup.get("site_id") or "")
        faults = rollup.get("faults") or {}
        for code, count in (faults.get("active_by_code") or {}).items():
            key = (site_id, str(code), "")
            totals[key] += float(count) * hours_per_sample
        fdd = rollup.get("fdd_batch") or {}
        for code, samples in (fdd.get("flagged_samples_by_code") or {}).items():
            key = (site_id, str(code), "")
            totals[key] += float(samples) * hours_per_sample / max(
                1, int(fdd.get("flagged_runs") or 1)
            )
    return [
        {
            "site_id": site,
            "fault_code": code,
            "equipment": equipment or "—",
            "elapsed_hours": round(hours, 2),
        }
        for (site, code, equipment), hours in sorted(totals.items())
    ]
