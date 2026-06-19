"""RCx DOCX placeholder hints from BRICK model / chart catalog (no docx dependency)."""

from __future__ import annotations

from typing import Any

SCREENSHOT_LABEL = "[ INSERT SCREENSHOT HERE ]"

# Building-level chart ids → analyst guidance when pasting Plotly snips.
CHART_INSERT_HINTS: dict[str, str] = {
    "ahu_sat_vs_setpoint": (
        "AHU system — plot supply air temperature vs discharge/setpoint. "
        "Use Trend plot or RCx gallery; overlay FDD SAT/flatline faults if present."
    ),
    "ahu_duct_static_vs_setpoint": (
        "AHU system — plot duct static pressure vs setpoint while fan modulates. "
        "Look for fan pinned high with pressure below setpoint."
    ),
    "vav_zone_temp": (
        "VAV terminal — plot zone temperature with heating/cooling setpoints. "
        "Prioritize zones with comfort faults in the fault table."
    ),
    "fault_hours_by_severity": "Summary bar chart — fault hours grouped by severity.",
    "fault_hours_by_equipment": "Summary bar chart — fault hours grouped by equipment.",
    "building_inventory": "Building inventory vs active fault count from BRICK model.",
}

FAMILY_LABELS: dict[str, str] = {
    "ahu": "Air handling unit (AHU/RTU)",
    "vav": "VAV terminal",
    "zone": "Zone / FCU / bench box",
    "hws": "Hot water / boiler plant",
    "chiller": "Chiller plant",
    "oat_weather": "Outside air vs weather",
    "building": "Building overview",
    "custom": "Custom point trend",
}


def _catalog_by_id(catalog: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in catalog or []:
        if isinstance(row, dict):
            cid = str(row.get("chart_id") or "").strip()
            if cid:
                out[cid] = row
    return out


def _equipment_chart_by_id(charts: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in charts or []:
        if isinstance(row, dict):
            cid = str(row.get("chart_id") or "").strip()
            if cid:
                out[cid] = row
    return out


def _preview_by_id(previews: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in previews or []:
        if isinstance(row, dict):
            cid = str(row.get("chart_id") or "").strip()
            if cid:
                out[cid] = row
    return out


def chart_placeholder_spec(
    chart_id: str,
    *,
    equipment_charts: list[dict[str, Any]] | None = None,
    catalog: list[dict[str, Any]] | None = None,
    chart_previews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve title, columns, and paste instructions for one chart placeholder."""
    cid = str(chart_id or "").strip()
    eq_map = _equipment_chart_by_id(equipment_charts)
    cat_map = _catalog_by_id(catalog)
    prev_map = _preview_by_id(chart_previews)

    eq = eq_map.get(cid)
    cat = cat_map.get(cid)
    prev = prev_map.get(cid)

    if eq:
        family = str(eq.get("family") or "equipment")
        cols = [str(c) for c in (eq.get("columns") or []) if c]
        title = str(eq.get("title") or cid)
        system = FAMILY_LABELS.get(family, family.replace("_", " ").title())
        hint = (
            f"{system} — paste a trend for {eq.get('equipment_name') or eq.get('equipment_id') or 'equipment'}. "
            f"Historian columns: {', '.join(cols) if cols else '—'}."
        )
        return {
            "chart_id": cid,
            "title": title,
            "subtitle": f"Columns: {', '.join(cols)}" if cols else "Equipment trend — paste Plotly snip",
            "instruction": hint,
            "columns": cols,
            "equipment_type": family.upper(),
            "family": family,
            "narrative": str((prev or {}).get("narrative") or "").strip(),
            "available": True,
        }

    title = str((cat or {}).get("title") or cid)
    roles = [str(r) for r in ((cat or {}).get("required_roles") or []) if r]
    eq_type = str((cat or {}).get("equipment_type") or "building")
    hint = CHART_INSERT_HINTS.get(cid, f"Paste Plotly trend for {title}.")
    if roles:
        hint = f"{hint} Required BRICK roles: {', '.join(roles)}."
    cols: list[str] = []
    stats = prev.get("stats") if isinstance(prev, dict) and isinstance(prev.get("stats"), dict) else {}
    if stats.get("columns"):
        cols = [str(c) for c in stats.get("columns") or [] if c]

    return {
        "chart_id": cid,
        "title": title,
        "subtitle": f"Building trend — roles: {', '.join(roles)}" if roles else "Building trend — paste Plotly snip",
        "instruction": hint,
        "columns": cols,
        "equipment_type": eq_type,
        "family": eq_type.lower(),
        "narrative": str((prev or {}).get("narrative") or "").strip(),
        "available": True,
    }


def disabled_chart_notes(disabled: list[dict[str, Any]] | None) -> list[str]:
    """Human-readable gaps when BRICK roles or historian data are missing."""
    notes: list[str] = []
    for row in disabled or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("chart_id") or "Chart")
        reason = str(row.get("reason") or "unavailable")
        roles = row.get("required_roles") or []
        role_txt = f" (roles: {', '.join(str(r) for r in roles)})" if roles else ""
        notes.append(f"{title}{role_txt} — {reason}")
    return notes


def rule_sensor_placeholder(rule: dict[str, Any]) -> list[dict[str, str]]:
    """Per-sensor screenshot rows for assigned FDD rules."""
    sensors = rule.get("sensors") if isinstance(rule.get("sensors"), list) else []
    rows: list[dict[str, str]] = []
    for s in sensors:
        if not isinstance(s, dict):
            continue
        label = str(s.get("label") or s.get("column") or "sensor")
        col = str(s.get("column") or "")
        brick = str(s.get("brick_type") or "")
        eq = str(s.get("equipment_id") or "")
        instruction = f"Trend {label}"
        if col:
            instruction += f" — historian column `{col}`"
        if brick:
            instruction += f" ({brick})"
        if eq:
            instruction += f" on equipment {eq}"
        instruction += ". Paste screenshot even if rule did not flag in this window."
        rows.append(
            {
                "label": label,
                "column": col,
                "brick_type": brick,
                "equipment_id": eq,
                "instruction": instruction,
            }
        )
    if not rows:
        rows.append(
            {
                "label": str(rule.get("rule_name") or "Rule"),
                "column": "",
                "brick_type": "",
                "equipment_id": "",
                "instruction": "Bind points in Model & assignments, then paste a trend for the rule inputs.",
            }
        )
    return rows
