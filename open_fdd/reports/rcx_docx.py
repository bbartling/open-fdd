"""Edge RCx DOCX report builder — read-only, selectable sections/charts."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from open_fdd.reports.charts import bar_chart_png
from open_fdd.reports.fault_hours import aggregate_fault_hours


DEFAULT_SECTIONS = [
    "executive_summary",
    "fault_analytics",
    "ahu_analytics",
    "vav_analytics",
    "runtime_analytics",
    "model_health",
    "recommendations",
    "appendix_faults",
    "appendix_missing_roles",
]

DEFAULT_CHARTS = [
    "fault_hours_by_severity",
    "fault_hours_by_equipment",
    "fault_hours_by_code",
    "active_faults_table",
]


def _recommendations(rows: list[dict[str, Any]], warnings: list[str]) -> list[str]:
    recs: list[str] = []
    for row in rows[:5]:
        eq = row.get("equipment") or "equipment"
        name = row.get("fault_name") or row.get("fault_code") or "fault"
        recs.append(f"Review {eq} for {name} — ~{row.get('elapsed_hours', 0)} h elapsed in lookback.")
    for w in warnings[:5]:
        if "flatline" in w.lower():
            recs.append("Verify sensor wiring/calibration if flatline faults persist.")
        elif "static" in w.lower() or "duct" in w.lower():
            recs.append("Review duct static pressure reset if pressure exceeds setpoint for extended periods.")
        elif "comfort" in w.lower() or "zone" in w.lower():
            recs.append("Investigate VAV zones with high comfort fault hours and saturated dampers.")
    if not recs:
        recs.append("No critical recommendations from current snapshot; continue monitoring.")
    return recs[:12]


def build_rcx_docx(
    *,
    site_id: str,
    site_name: str,
    window: dict[str, str | None],
    fault_rows: list[dict[str, Any]],
    overview: dict[str, Any] | None = None,
    sections: list[str] | None = None,
    charts: list[str] | None = None,
    warnings: list[str] | None = None,
    equipment_notes: list[dict[str, Any]] | None = None,
) -> bytes:
    from docx import Document
    from docx.shared import Inches

    enabled_sections = set(sections or DEFAULT_SECTIONS)
    enabled_charts = set(charts or DEFAULT_CHARTS)
    doc = Document()
    doc.add_heading("Open-FDD RCx Report", level=0)
    doc.add_paragraph(f"Building / site: {site_name}")
    doc.add_paragraph(f"Edge instance / site ID: {site_id}")
    if window.get("start") or window.get("end"):
        doc.add_paragraph(f"Report window: {window.get('start') or '—'} → {window.get('end') or '—'}")
    doc.add_paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    doc.add_paragraph(
        "Read-only analytics report. No BACnet writes, commands, overrides, or setpoint changes."
    )

    ov = overview or {}
    by_sev = aggregate_fault_hours(fault_rows, group_by="severity")
    by_eq = aggregate_fault_hours(fault_rows, group_by="equipment")
    by_code = aggregate_fault_hours(fault_rows, group_by="fault_code")

    if "executive_summary" in enabled_sections:
        doc.add_heading("Executive summary", level=1)
        doc.add_paragraph(f"Active faults: {ov.get('active_faults', len(fault_rows))}")
        doc.add_paragraph(f"Total elapsed fault hours (est.): {ov.get('total_fault_hours', 0)}")
        if by_eq:
            doc.add_paragraph(f"Worst equipment: {by_eq[0].get('group')} (~{by_eq[0].get('elapsed_hours')} h)")
        for w in (warnings or [])[:8]:
            doc.add_paragraph(f"• {w}")

    if "fault_analytics" in enabled_sections:
        doc.add_heading("Fault analytics", level=1)
        if "fault_hours_by_severity" in enabled_charts and by_sev:
            png = bar_chart_png(
                "Fault hours by severity",
                [r["group"] for r in by_sev],
                [r["elapsed_hours"] for r in by_sev],
                ylabel="Hours (est.)",
            )
            doc.add_picture(io.BytesIO(png), width=Inches(5.5))
        if "fault_hours_by_equipment" in enabled_charts and by_eq:
            png = bar_chart_png(
                "Fault hours by equipment",
                [r["group"] for r in by_eq[:12]],
                [r["elapsed_hours"] for r in by_eq[:12]],
                ylabel="Hours (est.)",
            )
            doc.add_picture(io.BytesIO(png), width=Inches(5.5))
        if "fault_hours_by_code" in enabled_charts and by_code:
            png = bar_chart_png(
                "Fault hours by fault code",
                [r["group"] for r in by_code[:12]],
                [r["elapsed_hours"] for r in by_code[:12]],
                ylabel="Hours (est.)",
            )
            doc.add_picture(io.BytesIO(png), width=Inches(5.5))
        if "active_faults_table" in enabled_charts or not enabled_charts:
            doc.add_paragraph("Active faults:")
            for row in fault_rows[:30]:
                doc.add_paragraph(
                    f"{row.get('equipment')} ({row.get('equipment_type') or '—'}) — "
                    f"{row.get('severity')}: {row.get('fault_name') or row.get('fault_code')} "
                    f"[~{row.get('elapsed_hours')} h, "
                    f"{row.get('samples_flagged')}/{row.get('samples_evaluated')} samples]"
                )

    if "ahu_analytics" in enabled_sections:
        doc.add_heading("AHU analytics", level=1)
        ahu_rows = [r for r in fault_rows if str(r.get("equipment_type") or "").upper() == "AHU"]
        if ahu_rows:
            for row in ahu_rows[:10]:
                doc.add_paragraph(
                    f"{row.get('equipment')}: {row.get('fault_name')} — ~{row.get('elapsed_hours')} h"
                )
        else:
            doc.add_paragraph("No AHU fault rows in selected window.")

    if "vav_analytics" in enabled_sections:
        doc.add_heading("VAV zone analytics", level=1)
        vav_rows = [r for r in fault_rows if "VAV" in str(r.get("equipment_type") or "").upper()]
        if vav_rows:
            for row in vav_rows[:15]:
                doc.add_paragraph(
                    f"{row.get('equipment')}: {row.get('fault_name')} — ~{row.get('elapsed_hours')} h"
                )
        else:
            doc.add_paragraph("No VAV fault rows in selected window.")

    if "runtime_analytics" in enabled_sections:
        doc.add_heading("Runtime analytics", level=1)
        doc.add_paragraph(
            "Runtime estimates require fan status/speed historian points; "
            "values labeled estimated when motor run-hour points are absent."
        )

    if "model_health" in enabled_sections:
        doc.add_heading("BACnet / model health", level=1)
        mh = ov.get("model_health") if isinstance(ov.get("model_health"), dict) else {}
        for label, key in (
            ("Devices", "device_count"),
            ("Points", "point_count"),
            ("Equipment", "equipment_count"),
            ("Stale points", "stale_point_count"),
        ):
            if key in mh:
                doc.add_paragraph(f"{label}: {mh[key]}")

    if "recommendations" in enabled_sections:
        doc.add_heading("Recommendations", level=1)
        for rec in _recommendations(fault_rows, warnings or []):
            doc.add_paragraph(f"• {rec}")

    if "appendix_faults" in enabled_sections:
        doc.add_heading("Appendix: fault table", level=1)
        for row in fault_rows:
            doc.add_paragraph(
                f"{row.get('fault_code')} | {row.get('equipment')} | {row.get('severity')} | "
                f"{row.get('elapsed_hours')} h"
            )

    if "appendix_missing_roles" in enabled_sections:
        doc.add_heading("Appendix: missing point roles", level=1)
        missing = ov.get("missing_roles") if isinstance(ov.get("missing_roles"), list) else []
        if missing:
            for m in missing[:40]:
                doc.add_paragraph(f"• {m}")
        else:
            doc.add_paragraph("None recorded.")

    if equipment_notes:
        doc.add_heading("Equipment notes", level=1)
        for note in equipment_notes[:20]:
            doc.add_paragraph(str(note.get("text") or note))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
