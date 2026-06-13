"""Paragraph mechanical summary from Edge FDD query presets (React Data Model parity)."""

from __future__ import annotations

from typing import Any

from portfolio.central.edge_registry import resolve_site_config, resolve_token
from portfolio.collector.edge_client import EdgeClient

# Same preset ids as workspace/dashboard DataModelSparqlPanel FDD buttons
_NARRATIVE_PRESETS = (
    "ahus_vavs_zones",
    "equipment_to_points",
    "missing_rule_bindings",
    "orphan_points",
    "rule_coverage_by_equipment_type",
)


def _run_preset(client: EdgeClient, preset_id: str, token: str) -> dict[str, Any]:
    return client.get_fdd_query_preset(preset_id, token=token)


def build_mechanical_narrative(site_id: str) -> dict[str, Any]:
    """Read-only narrative using Edge /api/model/fdd-query-presets/*."""
    site = resolve_site_config(site_id)
    client = EdgeClient(site.base_url)
    token = resolve_token(site)

    ahus = vavs = zones = 0
    point_rows = 0
    missing_bindings = 0
    orphan_points = 0
    coverage_lines: list[str] = []

    try:
        hvac = _run_preset(client, "ahus_vavs_zones", token)
        for row in hvac.get("rows") or []:
            if not isinstance(row, dict):
                continue
            et = str(row.get("equipment_type") or row.get("type") or "").upper()
            if "AHU" in et:
                ahus += 1
            elif "VAV" in et:
                vavs += 1
            elif "ZONE" in et:
                zones += 1
    except RuntimeError:
        pass

    try:
        eq_pts = _run_preset(client, "equipment_to_points", token)
        point_rows = int(eq_pts.get("row_count") or len(eq_pts.get("rows") or []))
    except RuntimeError:
        pass

    try:
        miss = _run_preset(client, "missing_rule_bindings", token)
        missing_bindings = int(miss.get("row_count") or len(miss.get("rows") or []))
    except RuntimeError:
        pass

    try:
        orphan = _run_preset(client, "orphan_points", token)
        orphan_points = int(orphan.get("row_count") or len(orphan.get("rows") or []))
    except RuntimeError:
        pass

    try:
        cov = _run_preset(client, "rule_coverage_by_equipment_type", token)
        for row in (cov.get("rows") or [])[:6]:
            if isinstance(row, dict):
                et = row.get("equipment_type") or row.get("group")
                cnt = row.get("rule_count") or row.get("count")
                if et is not None:
                    coverage_lines.append(f"{et}: {cnt} rule(s)")
    except RuntimeError:
        pass

    model_health = client.get_model_health(token=token)
    counts = model_health.get("counts") if isinstance(model_health.get("counts"), dict) else {}
    bacnet = client.get_bacnet_poll_status(token=token)

    paragraphs = [
        f"{site.name} ({site_id}) at {site.base_url} — BRICK model via Edge FDD query presets "
        f"(same endpoints as the OpenFDD Edge Data Model tab).",
        (
            f"Mechanical inventory: {ahus} AHU(s), {vavs} VAV(s), {zones} zone(s) "
            f"from the AHUs/VAVs/Zones preset; {point_rows} equipment→point row(s) in the model graph."
        ),
        (
            f"Model health: {counts.get('equipment', '—')} equipment, {counts.get('points', '—')} points. "
            f"FDD coverage gaps: {missing_bindings} rule(s) with missing bindings, "
            f"{orphan_points} orphan/unused sensor point(s)."
        ),
    ]
    if coverage_lines:
        paragraphs.append("Rule coverage by equipment type: " + "; ".join(coverage_lines) + ".")
    if bacnet.get("last_poll_at"):
        paragraphs.append(
            f"BACnet poll: {bacnet.get('enabled_points', '—')} enabled point(s); "
            f"last poll {bacnet.get('last_poll_at')}."
        )

    return {
        "site_id": site_id,
        "narrative": "\n\n".join(paragraphs),
        "presets_used": list(_NARRATIVE_PRESETS),
        "counts": {
            "ahus": ahus,
            "vavs": vavs,
            "zones": zones,
            "equipment_point_rows": point_rows,
            "missing_rule_bindings": missing_bindings,
            "orphan_points": orphan_points,
        },
    }
