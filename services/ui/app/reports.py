"""Export summaries and simple reports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.rules.base import RuleResult


def results_summary_table(results: list[RuleResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        metrics = getattr(r, "metrics", None) or {}
        # OAT-METEO uses always-gate; % of window is not meaningful — prefer °F deviation.
        fault_pct = None if r.rule_id == "OAT-METEO" else r.fault_pct
        rows.append(
            {
                "rule_id": r.rule_id,
                "site_id": r.site_id,
                "building_id": r.building_id,
                "equipment_id": r.equipment_id,
                "equipment_type": r.equipment_type,
                "status": r.status,
                "applicable": r.applicable,
                "missing_roles": ", ".join(r.missing_roles),
                "fault_hours": r.fault_hours,
                "fault_pct": fault_pct,
                "oat_mean_abs_diff_f": metrics.get("oat_meteo_mean_abs_diff_f"),
                "oat_max_abs_diff_f": metrics.get("oat_meteo_max_abs_diff_f"),
                "fault_samples": r.fault_sample_count,
                "notes": r.notes,
            }
        )
    return pd.DataFrame(rows)


def debug_frame(result: RuleResult) -> pd.DataFrame:
    if result.debug is not None:
        return result.debug
    if result.raw_fault is None:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "raw_fault": result.raw_fault.astype(int),
            "confirmed_fault": result.confirmed_fault.astype(int) if result.confirmed_fault is not None else 0,
        }
    )


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=True).encode("utf-8")


def markdown_report(
    *,
    building_id: str,
    data_source: str,
    results: list[RuleResult],
    engineer_notes: dict[str, str],
    params_snapshot: dict[str, Any],
) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# FDD Demo Report — {building_id}",
        "",
        f"Generated: {ts}",
        f"Data source: {data_source}",
        "",
        "## Fault summary",
        "",
    ]
    summary = results_summary_table(results)
    if not summary.empty:
        cols = list(summary.columns)
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join("---" for _ in cols) + " |")
        for _, row in summary.iterrows():
            lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    else:
        lines.append("_No rule results._")
    lines.extend(["", "## Tuning parameters", ""])
    for k, v in sorted(params_snapshot.items()):
        lines.append(f"- **{k}**: {v}")
    if engineer_notes:
        lines.extend(["", "## Engineer notes", ""])
        for section, note in engineer_notes.items():
            if note.strip():
                lines.append(f"### {section}")
                lines.append(note.strip())
                lines.append("")
    return "\n".join(lines)


def html_report(md: str) -> str:
    body = md.replace("\n", "<br>\n")
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>FDD Report</title></head><body>{body}</body></html>"
