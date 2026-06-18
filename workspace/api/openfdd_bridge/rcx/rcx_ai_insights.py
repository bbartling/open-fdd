"""AI analyst assessment for RCx DOCX reports (Ollama + Arrow-native deterministic fallback)."""

from __future__ import annotations

import json
from typing import Any

from .. import ollama_client
from ..brick_model_context import build_insight_brick_payload, catalog_entries_for_codes
from ..building_insight import fault_sentences_from_alerts
from ..operational_analytics import analytics_lookback_days, methodology_prompt_blurb
from .rcx_narrative import build_chart_narrative

RCX_INSIGHT_TIMEOUT_S = 90.0
MAX_PARAGRAPH_CHARS = 1200
FAULT_DUTY_THRESHOLD_PCT = 5.0


def _fault_codes(rows: list[dict[str, Any]]) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for row in rows:
        code = str(row.get("fault_code") or "").strip().upper()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _slim_chart_previews(previews: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for prev in previews[:limit]:
        if not isinstance(prev, dict):
            continue
        stats = prev.get("stats") if isinstance(prev.get("stats"), dict) else {}
        out.append(
            {
                "chart_id": prev.get("chart_id"),
                "title": prev.get("title"),
                "equipment_type": prev.get("equipment_type"),
                "narrative": (str(prev.get("narrative") or ""))[:480],
                "stats_bullets": (stats.get("stats_bullets") or prev.get("stats_bullets") or [])[:6],
                "fault_percent": stats.get("fault_percent"),
                "fault_hours": stats.get("fault_hours"),
                "total_hours": stats.get("total_hours"),
                "series_stats": stats.get("series_stats"),
                "row_count": stats.get("row_count") or prev.get("row_count"),
            }
        )
    return out


def _slim_fault_rows(rows: list[dict[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "equipment": row.get("equipment"),
                "equipment_type": row.get("equipment_type"),
                "fault_code": row.get("fault_code"),
                "fault_name": row.get("fault_name"),
                "severity": row.get("severity"),
                "elapsed_hours": row.get("elapsed_hours"),
                "samples_flagged": row.get("samples_flagged"),
                "samples_evaluated": row.get("samples_evaluated"),
            }
        )
    return out


def _slim_rules(rules: list[dict[str, Any]], *, limit: int = 16) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rule in rules[:limit]:
        if not isinstance(rule, dict):
            continue
        sensors = rule.get("sensors") if isinstance(rule.get("sensors"), list) else []
        out.append(
            {
                "rule_id": rule.get("rule_id"),
                "rule_name": rule.get("rule_name"),
                "fault_code": rule.get("fault_code"),
                "severity": rule.get("severity"),
                "sensor_count": len(sensors),
                "sensors": [
                    {
                        "label": s.get("label"),
                        "column": s.get("column"),
                        "brick_type": s.get("brick_type"),
                    }
                    for s in sensors[:6]
                    if isinstance(s, dict)
                ],
            }
        )
    return out


def _slim_motors(rows: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "equipment_name": row.get("equipment_name"),
                "point_label": row.get("point_label"),
                "column": row.get("column"),
                "hours_in_window": row.get("hours_in_window"),
                "weekly_hours_est": row.get("weekly_hours_est"),
            }
        )
    return out


def compact_rcx_context(
    *,
    site_id: str,
    site_name: str,
    window: dict[str, Any],
    fault_rows: list[dict[str, Any]],
    overview: dict[str, Any] | None,
    chart_previews: list[dict[str, Any]],
    report_context: dict[str, Any],
    mechanical_summary: dict[str, Any] | None,
) -> str:
    """Arrow-native JSON context for RCx AI assessment (no pandas)."""
    ov = overview or {}
    mech = mechanical_summary if isinstance(mechanical_summary, dict) else {}
    counts = mech.get("counts") if isinstance(mech.get("counts"), dict) else {}
    ctx = report_context or {}
    overrides = ctx.get("overrides") if isinstance(ctx.get("overrides"), dict) else {}
    codes = _fault_codes(fault_rows)

    brick: dict[str, Any] = {}
    alerts: list[dict[str, Any]] = []
    try:
        from ..building_status import collect_status

        status = collect_status()
        brick = build_insight_brick_payload(status)
        alerts = [a for a in (status.get("alerts") or []) if isinstance(a, dict)]
    except Exception:
        pass

    zone_slim: dict[str, Any] = {}
    device_slim: dict[str, Any] = {}
    try:
        from ..zone_temp_analytics import get_zone_temp_snapshot, slim_zone_for_llm
        from ..device_poll_health import get_device_poll_snapshot, slim_devices_for_llm

        zone_snap = get_zone_temp_snapshot(force=False)
        zone_slim = slim_zone_for_llm(zone_snap, max_zones=8, max_systems=3, max_zones_per_system=6)
        device_slim = slim_devices_for_llm(get_device_poll_snapshot(force=False))
    except Exception:
        pass

    payload: dict[str, Any] = {
        "report_type": "rcx_docx",
        "site_id": site_id,
        "site_name": site_name,
        "window": window,
        "methodology_blurb": methodology_prompt_blurb(),
        "lookback_days": analytics_lookback_days(),
        "mechanical_summary": {
            "narrative": (str(mech.get("narrative") or ""))[:600],
            "counts": counts,
            "equipment_counts": mech.get("equipment_counts"),
            "ahus": (mech.get("ahus") or [])[:8],
            "vavs": (mech.get("vavs") or [])[:12],
            "rtus": (mech.get("rtus") or [])[:8],
            "data_readiness_score": mech.get("data_readiness_score"),
            "active_faults": mech.get("active_faults") or ov.get("active_faults"),
            "total_fault_hours": mech.get("total_fault_hours") or ov.get("total_fault_hours"),
        },
        "model_health": mech.get("model_health") if isinstance(mech.get("model_health"), dict) else ov.get("model_health"),
        "fault_summary": {
            "active_faults": ov.get("active_faults", len(fault_rows)),
            "total_fault_hours": ov.get("total_fault_hours"),
            "codes": codes[:16],
        },
        "fault_rows": _slim_fault_rows(fault_rows),
        "fault_sentences": fault_sentences_from_alerts(alerts, limit=12),
        "fault_catalog": catalog_entries_for_codes(codes, limit=10),
        "chart_previews": _slim_chart_previews(chart_previews),
        "assigned_fdd_rules": _slim_rules(ctx.get("assigned_rules") or []),
        "motor_runtime": _slim_motors(ctx.get("motor_runtime") or []),
        "bacnet_overrides": overrides,
        "brick_model": brick.get("brick_model") or {},
        "faults_linked": brick.get("faults_linked") or [],
        "zone_temps": zone_slim,
        "device_poll_health": device_slim,
        "legacy_fault_threshold_pct": FAULT_DUTY_THRESHOLD_PCT,
    }
    return json.dumps(payload, separators=(",", ":"))


def build_override_commentary(overrides: dict[str, Any]) -> list[str]:
    """Plain-language BACnet priority-array override notes."""
    lines: list[str] = []
    ov_list = overrides.get("overrides") if isinstance(overrides.get("overrides"), list) else []
    op_pri = int(overrides.get("operator_priority") or 8)
    total = int(overrides.get("override_count") or len(ov_list))
    if total <= 0:
        lines.append(
            "No active BACnet priority-array overrides were recorded in the supervisory scan — "
            "setpoints and outputs appear to be under normal automatic control."
        )
        return lines

    p8 = [o for o in ov_list if isinstance(o, dict) and o.get("operator_p8")]
    other = [o for o in ov_list if isinstance(o, dict) and not o.get("operator_p8")]
    lines.append(
        f"The Edge recorded {total} BACnet override slot(s) across the polled device tree. "
        f"Operator priority {op_pri} (manual human writes) accounts for {len(p8)} point(s); "
        f"other supervisory priorities account for {len(other)}."
    )
    if p8:
        samples = ", ".join(
            f"{o.get('point') or o.get('oid')} on device {o.get('device')}"
            for o in p8[:4]
        )
        lines.append(
            f"Operator P{op_pri} overrides ({samples}{'…' if len(p8) > 4 else ''}) "
            "bypass automatic sequences — common RCx findings include fans left in hand, "
            "SAT or static setpoints pinned, or dampers forced open/closed during troubleshooting. "
            "Clear overrides after work is complete and verify return to automatic control."
        )
    if other:
        lines.append(
            f"{len(other)} override(s) sit at non-operator BACnet priorities — often BAS schedule "
            "writes, maintenance tools, or stuck supervisory commands. Distinguish intentional "
            "commissioning holds from hygiene issues that mask underlying control faults."
        )
    return lines


def build_rule_assessments(
    rules: list[dict[str, Any]],
    fault_rows: list[dict[str, Any]],
    *,
    mech: dict[str, Any] | None = None,
) -> list[str]:
    """Assess whether Rule Lab bindings look appropriate for the modeled HVAC."""
    lines: list[str] = []
    if not rules:
        lines.append(
            "No enabled Rule Lab rules are assigned — FDD coverage is incomplete for RCx analytics. "
            "Bind Arrow/SQL rules to AHU, VAV, and plant points before relying on fault overlays."
        )
        return lines

    unbound = [r for r in rules if not (r.get("sensors") if isinstance(r.get("sensors"), list) else [])]
    bound = len(rules) - len(unbound)
    lines.append(
        f"{bound} of {len(rules)} enabled rule(s) have historian sensor bindings suitable for trend overlays."
    )
    if unbound:
        names = ", ".join(str(r.get("rule_name") or r.get("rule_id")) for r in unbound[:4])
        lines.append(
            f"Rules missing point bindings ({names}{'…' if len(unbound) > 4 else ''}) cannot drive "
            "chart fault overlays — assign BRICK points in Model & assignments before field walkdown."
        )

    counts = (mech or {}).get("counts") if isinstance((mech or {}).get("counts"), dict) else {}
    ahu_n = int(counts.get("ahus") or counts.get("ahu") or 0)
    vav_n = int(counts.get("vavs") or counts.get("vav") or 0)
    ahu_rules = [r for r in rules if "AHU" in str(r.get("fault_code") or "").upper() or "SAT" in str(r.get("rule_name") or "").upper()]
    vav_rules = [r for r in rules if "VAV" in str(r.get("fault_code") or "").upper() or "zone" in str(r.get("rule_name") or "").lower()]
    if ahu_n and not ahu_rules:
        lines.append(
            f"The model shows {ahu_n} AHU(s) but no AHU-oriented FDD rules — consider SAT, duct static, "
            "and economizer rules aligned with ASHRAE G36 fault detection patterns."
        )
    if vav_n and not vav_rules:
        lines.append(
            f"{vav_n} VAV terminal(s) are modeled without zone-comfort rules — VAV-C/VAV-E style rules "
            "help catch rogue zones that drive simultaneous heating and cooling upstream."
        )

    active_codes = {str(r.get("fault_code") or "").upper() for r in fault_rows}
    for rule in rules[:8]:
        code = str(rule.get("fault_code") or "").upper()
        if not code:
            continue
        if code in active_codes:
            lines.append(
                f"Rule «{rule.get('rule_name')}» ({code}) is firing in this window — "
                "catalog semantics and trend screenshots should be reviewed together before tuning thresholds."
            )
    return lines[:10]


def _motor_schedule_note(motors: list[dict[str, Any]], window_hours: float) -> str | None:
    if window_hours <= 0 or not motors:
        return None
    for m in motors:
        hrs = float(m.get("hours_in_window") or 0)
        if hrs >= window_hours * 0.92:
            name = m.get("equipment_name") or m.get("column") or "supply fan"
            return (
                f"{name} ran ~{hrs:.0f} h of a {window_hours:.0f}-h window — near 24/7 operation. "
                "Legacy OpenFDD RCx guidance recommends occupancy-based fan schedules when total hours "
                "match motor runtime."
            )
    return None


def build_fallback_insights(
    *,
    site_name: str,
    window: dict[str, Any],
    fault_rows: list[dict[str, Any]],
    overview: dict[str, Any] | None,
    chart_previews: list[dict[str, Any]],
    report_context: dict[str, Any],
    mechanical_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Deterministic RCx narrative when Ollama is disabled or unreachable."""
    ov = overview or {}
    mech = mechanical_summary if isinstance(mechanical_summary, dict) else {}
    counts = mech.get("counts") if isinstance(mech.get("counts"), dict) else {}
    ctx = report_context or {}
    overrides = ctx.get("overrides") if isinstance(ctx.get("overrides"), dict) else {}
    win_h = float(window.get("hours") or 0)

    paragraphs: list[str] = []
    narrative = str(mech.get("narrative") or "").strip()
    ahu_n = counts.get("ahus") or counts.get("ahu") or "—"
    vav_n = counts.get("vavs") or counts.get("vav") or "—"
    zone_n = counts.get("zones") or "—"
    arch = (
        f"{site_name} is modeled with {ahu_n} AHU(s), {vav_n} VAV(s), and {zone_n} zone(s) "
        "in the BRICK graph. PyArrow historian stats in this report window quantify how those "
        "systems actually performed — not just how they were commissioned on paper."
    )
    if narrative:
        arch += f" {narrative[:320]}"
    paragraphs.append(arch)

    active = int(ov.get("active_faults") or len(fault_rows))
    fault_h = float(ov.get("total_fault_hours") or 0)
    readiness = mech.get("data_readiness_score")
    health_bits = [
        f"{active} active fault(s) (~{fault_h:.1f} h elapsed in lookback)",
    ]
    if readiness is not None:
        health_bits.append(f"data readiness score {readiness}/100")
    paragraphs.append(
        "Operational health: " + "; ".join(health_bits) + ". "
        "Use fault-hour charts and equipment tables in this report to prioritize walkdown order — "
        "longest elapsed hours usually indicate chronic control or hygiene issues, not one-off glitches."
    )

    chart_insights: list[dict[str, Any]] = []
    high_duty: list[str] = []
    for prev in chart_previews:
        if not isinstance(prev, dict):
            continue
        stats = prev.get("stats") if isinstance(prev.get("stats"), dict) else {}
        fault_pct = float(stats.get("fault_percent") or 0)
        title = str(prev.get("title") or prev.get("chart_id") or "Chart")
        text = str(prev.get("narrative") or "").strip()
        if not text:
            text = build_chart_narrative(
                chart_id=str(prev.get("chart_id") or ""),
                title=title,
                stats=stats,
                fault_summary={"active_faults": active},
            )
        chart_insights.append({"title": title, "narrative": text, "stats_bullets": stats.get("stats_bullets") or []})
        if fault_pct > FAULT_DUTY_THRESHOLD_PCT:
            high_duty.append(f"{title} ({fault_pct:.1f}% fault duty)")

    if chart_insights:
        lead = chart_insights[0]["narrative"]
        if high_duty:
            lead += (
                f" Charts exceeding the legacy {FAULT_DUTY_THRESHOLD_PCT:.0f}% fault-duty threshold: "
                + ", ".join(high_duty[:4])
                + "."
            )
        paragraphs.append(lead)
        for ci in chart_insights[1:4]:
            paragraphs.append(f"{ci['title']}: {ci['narrative']}")
    else:
        paragraphs.append(
            "Trend statistics were not available for the selected charts — expand historian coverage "
            "or bind BRICK roles before expecting plot-level RCx commentary."
        )

    rule_notes = build_rule_assessments(ctx.get("assigned_rules") or [], fault_rows, mech=mech)
    paragraphs.append(" ".join(rule_notes[:3]))

    override_notes = build_override_commentary(overrides)
    paragraphs.append(override_notes[0] if override_notes else "")

    motor_note = _motor_schedule_note(ctx.get("motor_runtime") or [], win_h)
    if motor_note:
        paragraphs.append(motor_note)

    paragraphs = [p.strip() for p in paragraphs if p and p.strip()]

    return {
        "source": "deterministic",
        "paragraphs": paragraphs[:8],
        "chart_insights": chart_insights[:8],
        "rule_assessments": rule_notes,
        "override_notes": override_notes,
        "error": "",
    }


def _ollama_rcx_assessment(context: str) -> tuple[list[str], str]:
    days = analytics_lookback_days()
    system = (
        "You are a senior HVAC retro-commissioning (RCx) engineer writing the client-facing "
        "'AI Analyst Assessment' section of a DOCX report. Facts come only from the JSON snapshot "
        f"(PyArrow historian stats, BRICK model, Rule Lab, BACnet overrides). Lookback is ~{days} days. "
        "Write 5–7 short paragraphs of plain English (no markdown, no bullet lists). "
        "Cover: (1) building HVAC architecture and system types from mechanical_summary and brick_model feeds; "
        "(2) operational health — faults, zone_temps, device_poll_health; "
        "(3) interpret chart_previews stats (fault_percent, series min/max/mean) — use legacy_fault_threshold_pct "
        "5% as 'high fault duty' guidance per ASHRAE G36 thinking; "
        "(4) assess assigned_fdd_rules — bindings appropriate for equipment? gaps? "
        "(5) bacnet_overrides — operator P8 human writes vs other priorities and hygiene impact; "
        "(6) prioritized RCx sell — energy, comfort, IAQ, what to fix first. "
        "Be confident and actionable for a building owner. Never invent equipment, passwords, or values."
    )
    user = f"RCx snapshot JSON:\n{context}\n\nAI Analyst Assessment:"
    result = ollama_client.chat(
        user,
        system=system,
        history=[],
        timeout=RCX_INSIGHT_TIMEOUT_S,
    )
    if not result.get("ok"):
        return [], str(result.get("error") or "ollama failed")
    raw = str(result.get("reply") or "").strip()
    if not raw:
        return [], "empty ollama reply"
    parts = [p.strip() for p in raw.replace("\r\n", "\n").split("\n\n") if p.strip()]
    if len(parts) == 1:
        parts = [p.strip() for p in raw.split(". ") if p.strip()]
        parts = [f"{p}." if not p.endswith(".") else p for p in parts]
    trimmed: list[str] = []
    for p in parts:
        if len(p) > MAX_PARAGRAPH_CHARS:
            p = p[: MAX_PARAGRAPH_CHARS - 1].rstrip() + "…"
        trimmed.append(p)
    return trimmed[:10], ""


def generate_rcx_ai_insights(
    *,
    site_id: str,
    site_name: str,
    window: dict[str, Any],
    fault_rows: list[dict[str, Any]],
    overview: dict[str, Any] | None,
    chart_previews: list[dict[str, Any]],
    report_context: dict[str, Any],
    mechanical_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build AI analyst assessment for DOCX (Ollama when enabled, else deterministic)."""
    fallback = build_fallback_insights(
        site_name=site_name,
        window=window,
        fault_rows=fault_rows,
        overview=overview,
        chart_previews=chart_previews,
        report_context=report_context,
        mechanical_summary=mechanical_summary,
    )

    if not ollama_client.should_use_ollama_for_insight():
        return fallback

    context = compact_rcx_context(
        site_id=site_id,
        site_name=site_name,
        window=window,
        fault_rows=fault_rows,
        overview=overview,
        chart_previews=chart_previews,
        report_context=report_context,
        mechanical_summary=mechanical_summary,
    )
    paragraphs, err = _ollama_rcx_assessment(context)
    if paragraphs:
        out = dict(fallback)
        out["source"] = "ollama"
        out["paragraphs"] = paragraphs
        out["error"] = ""
        return out

    out = dict(fallback)
    out["error"] = err[:240]
    return out
