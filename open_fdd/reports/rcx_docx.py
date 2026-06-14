"""Edge RCx DOCX — professional template with screenshot placeholders + programmatic data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from open_fdd.reports.fault_hours import aggregate_fault_hours

DEFAULT_SECTIONS = [
    "executive_summary",
    "mechanical_summary",
    "trend_charts",
    "fault_analytics",
    "ahu_analytics",
    "vav_analytics",
    "analyst_insights",
    "runtime_analytics",
    "model_health",
    "recommendations",
    "appendix_faults",
    "appendix_missing_roles",
]

SCREENSHOT_LABEL = "[ INSERT SCREENSHOT HERE ]"


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


def _screenshot_placeholder(doc, *, title: str, subtitle: str = "") -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    doc.add_paragraph()
    box = doc.add_paragraph()
    box.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = box.add_run(SCREENSHOT_LABEL)
    run.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.add_run(title).italic = True
    if subtitle:
        sub = doc.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub.add_run(subtitle).font.size = Pt(9)


def _kv_table(doc, rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    for i, (k, v) in enumerate(rows):
        table.rows[i].cells[0].text = str(k)
        table.rows[i].cells[1].text = str(v)


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
    chart_previews: list[dict[str, Any]] | None = None,
    report_context: dict[str, Any] | None = None,
    equipment_bundle: dict[str, Any] | None = None,
) -> bytes:
    from docx import Document
    from docx.shared import Inches, Pt

    enabled_sections = set(sections or DEFAULT_SECTIONS)
    ctx = report_context or {}
    assigned_rules = ctx.get("assigned_rules") if isinstance(ctx.get("assigned_rules"), list) else []
    motor_rows = ctx.get("motor_runtime") if isinstance(ctx.get("motor_runtime"), list) else []
    overrides = ctx.get("overrides") if isinstance(ctx.get("overrides"), dict) else {}
    override_list = overrides.get("overrides") if isinstance(overrides.get("overrides"), list) else []

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    doc.add_heading("Retro-Commissioning Analytics Report", level=0)
    doc.add_paragraph(f"Building: {site_name}")
    doc.add_paragraph(f"Site ID: {site_id}")
    if equipment_bundle:
        doc.add_paragraph(
            f"Equipment report: {equipment_bundle.get('label') or equipment_bundle.get('bundle_id') or '—'}"
        )
    if window.get("start") or window.get("end"):
        doc.add_paragraph(f"Analysis window: {window.get('start') or '—'} → {window.get('end') or '—'}")
    doc.add_paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    doc.add_paragraph(
        "Read-only analytics export. Paste Plotly trend screenshots into the marked placeholders. "
        "No BACnet writes or overrides are performed by this report."
    )

    ov = overview or {}
    by_sev = aggregate_fault_hours(fault_rows, group_by="severity")
    by_eq = aggregate_fault_hours(fault_rows, group_by="equipment")
    by_code = aggregate_fault_hours(fault_rows, group_by="fault_code")

    if "executive_summary" in enabled_sections:
        doc.add_heading("Executive summary", level=1)
        _kv_table(
            doc,
            [
                ("Active faults", str(ov.get("active_faults", len(fault_rows)))),
                ("Total elapsed fault hours (est.)", str(ov.get("total_fault_hours", 0))),
                ("BACnet P8 overrides", str(ctx.get("override_count", 0))),
                ("Assigned FDD rules", str(len(assigned_rules))),
                ("Motor / fan points modeled", str(len(motor_rows))),
            ],
        )
        if by_eq:
            doc.add_paragraph(
                f"Worst equipment: {by_eq[0].get('group')} (~{by_eq[0].get('elapsed_hours')} h)"
            )
        for w in (warnings or [])[:6]:
            doc.add_paragraph(f"• {w}")

    if "mechanical_summary" in enabled_sections:
        doc.add_heading("Mechanical summary", level=1)
        mech = ov.get("mechanical_summary") if isinstance(ov.get("mechanical_summary"), dict) else {}
        narrative = str(mech.get("narrative") or "").strip()
        if narrative:
            for para in narrative.split("\n\n"):
                if para.strip():
                    doc.add_paragraph(para.strip())
        counts = mech.get("counts") if isinstance(mech.get("counts"), dict) else {}
        if counts:
            doc.add_paragraph(
                f"Inventory: {counts.get('ahus', counts.get('ahu', '—'))} AHU(s), "
                f"{counts.get('vavs', counts.get('vav', '—'))} VAV(s), "
                f"{counts.get('zones', '—')} zone(s)."
            )
        elif not narrative:
            doc.add_paragraph("Mechanical summary unavailable for this Edge snapshot.")

    if "trend_charts" in enabled_sections:
        doc.add_heading("Trend charts (engineer screenshots)", level=1)
        doc.add_paragraph(
            "Use the RCx Report Builder Plotly gallery or Trend plot tab. "
            "When the trend looks correct, snip the chart and paste into each placeholder below."
        )
        eq_charts = equipment_bundle.get("chart_ids") if isinstance(equipment_bundle, dict) else None
        if eq_charts:
            for cid in eq_charts:
                _screenshot_placeholder(doc, title=str(cid), subtitle="Equipment trend — paste Plotly snip")
        else:
            for spec_id in charts or ["ahu_sat_vs_setpoint", "ahu_duct_static_vs_setpoint", "vav_zone_temp"]:
                _screenshot_placeholder(doc, title=str(spec_id), subtitle="Building trend — paste Plotly snip")

    if "fault_analytics" in enabled_sections:
        doc.add_heading("Fault analytics", level=1)
        if by_sev:
            doc.add_paragraph("Fault hours by severity:")
            for row in by_sev:
                doc.add_paragraph(f"  {row.get('group')}: {row.get('elapsed_hours')} h")
        if by_eq:
            doc.add_paragraph("Fault hours by equipment:")
            for row in by_eq[:15]:
                doc.add_paragraph(f"  {row.get('group')}: {row.get('elapsed_hours')} h")
        if by_code:
            doc.add_paragraph("Fault hours by code:")
            for row in by_code[:15]:
                doc.add_paragraph(f"  {row.get('group')}: {row.get('elapsed_hours')} h")
        doc.add_paragraph("Active fault detail:")
        for row in fault_rows[:30]:
            doc.add_paragraph(
                f"{row.get('equipment')} ({row.get('equipment_type') or '—'}) — "
                f"{row.get('severity')}: {row.get('fault_name') or row.get('fault_code')} "
                f"[~{row.get('elapsed_hours')} h, "
                f"{row.get('samples_flagged')}/{row.get('samples_evaluated')} samples]"
            )

    if "ahu_analytics" in enabled_sections:
        doc.add_heading("AHU analytics", level=1)
        ahu_rows = [r for r in fault_rows if str(r.get("equipment_type") or "").upper() in ("AHU", "RTU")]
        if ahu_rows:
            for row in ahu_rows[:10]:
                doc.add_paragraph(
                    f"{row.get('equipment')}: {row.get('fault_name')} — ~{row.get('elapsed_hours')} h"
                )
        else:
            doc.add_paragraph("No AHU fault rows in selected window.")
        _screenshot_placeholder(doc, title="AHU overview trend", subtitle="SAT / static / OA-MAT-RAT")

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
        _screenshot_placeholder(doc, title="VAV zone comfort trend", subtitle="Zone temp vs setpoints")

    if "runtime_analytics" in enabled_sections:
        doc.add_heading("Runtime analytics (motor / fan / pump)", level=1)
        if motor_rows:
            doc.add_paragraph("Estimated run-hours from BRICK motor/fan/pump points (PyArrow historian):")
            table = doc.add_table(rows=1, cols=5)
            table.style = "Table Grid"
            hdr = table.rows[0].cells
            hdr[0].text = "Equipment"
            hdr[1].text = "Point"
            hdr[2].text = "Column"
            hdr[3].text = "Hours (window)"
            hdr[4].text = "Weekly est. (h)"
            for m in motor_rows[:20]:
                row = table.add_row().cells
                row[0].text = str(m.get("equipment_name") or "—")
                row[1].text = str(m.get("label") or "—")
                row[2].text = str(m.get("column") or "—")
                row[3].text = str(m.get("runtime_hours") or 0)
                row[4].text = str(m.get("weekly_hours_est") or 0)
        else:
            doc.add_paragraph(
                "No motor/fan/pump points detected in BRICK model. "
                "Tag Fan_Status, Pump_Status, or VFD speed sensors to enable runtime estimates."
            )
        _screenshot_placeholder(doc, title="Motor / fan runtime trend", subtitle="Weekly run-hours verification")

    if "model_health" in enabled_sections:
        doc.add_heading("BACnet / model health", level=1)
        mh = ov.get("model_health") if isinstance(ov.get("model_health"), dict) else {}
        _kv_table(
            doc,
            [
                (label, str(mh[key]))
                for label, key in (
                    ("Devices", "device_count"),
                    ("Points", "point_count"),
                    ("Equipment", "equipment_count"),
                    ("Stale points", "stale_point_count"),
                )
                if key in mh
            ],
        )
        if override_list:
            doc.add_paragraph(f"Active BACnet overrides: {len(override_list)}")
            for ov_row in override_list[:12]:
                if isinstance(ov_row, dict):
                    doc.add_paragraph(
                        f"  {ov_row.get('device_id') or ov_row.get('device') or '—'} "
                        f"{ov_row.get('object') or ov_row.get('object_id') or ''} "
                        f"priority {ov_row.get('priority') or '—'}"
                    )

    doc.add_heading("FDD rule trend screenshots", level=1)
    doc.add_paragraph(
        "For each assigned Rule Lab rule, paste a trend screenshot for the bound sensor columns "
        "(required even when no fault is active in the lookback window)."
    )
    if assigned_rules:
        for rule in assigned_rules:
            doc.add_heading(str(rule.get("rule_name") or rule.get("rule_id")), level=2)
            doc.add_paragraph(
                f"Fault code: {rule.get('fault_code') or '—'} · Severity: {rule.get('severity') or '—'}"
            )
            sensors = rule.get("sensors") if isinstance(rule.get("sensors"), list) else []
            if sensors:
                for s in sensors:
                    if not isinstance(s, dict):
                        continue
                    label = str(s.get("label") or s.get("column") or "sensor")
                    col = str(s.get("column") or "")
                    brick = str(s.get("brick_type") or "")
                    doc.add_paragraph(f"Sensor: {label} ({col}) {brick}")
                    _screenshot_placeholder(
                        doc,
                        title=f"{rule.get('rule_name')} — {label}",
                        subtitle=f"Historian column: {col}",
                    )
            else:
                _screenshot_placeholder(
                    doc,
                    title=str(rule.get("rule_name") or "Rule trend"),
                    subtitle="Bind points in Model & assignments",
                )
    else:
        doc.add_paragraph("No enabled Rule Lab rules found for this site.")

    if "recommendations" in enabled_sections:
        doc.add_heading("Recommendations", level=1)
        for rec in _recommendations(fault_rows, warnings or []):
            doc.add_paragraph(f"• {rec}")

    if "analyst_insights" in enabled_sections:
        doc.add_heading("Analyst insights", level=1)
        doc.add_paragraph(
            "Plain-language interpretation — add field notes here after reviewing trends and fault evidence."
        )

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

    import io

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
