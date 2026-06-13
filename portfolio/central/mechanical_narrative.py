"""Paragraph mechanical summary from Edge FDD query presets (React Data Model parity)."""

from __future__ import annotations

from typing import Any

from portfolio.central.edge_fetch import edge_client_for_site, run_parallel
from portfolio.central.equipment_classify import is_ahu, is_vav, is_zone
from portfolio.collector.edge_client import EdgeClient

# Same preset ids as workspace/dashboard DataModelSparqlPanel FDD buttons
_NARRATIVE_PRESETS = (
    "ahus_vavs_zones",
    "equipment_to_points",
    "missing_rule_bindings",
    "orphan_points",
    "rule_coverage_by_equipment_type",
)

_FAST_PRESETS = ("ahus_vavs_zones",)


def _run_preset(client: EdgeClient, preset_id: str, token: str) -> dict[str, Any]:
    return client.get_fdd_query_preset(preset_id, token=token)


def _count_hvac_row(row: dict[str, Any]) -> tuple[int, int, int]:
    """Return (ahu, vav, zone) increment tuple for one preset row."""
    hvac_class = str(row.get("hvac_class") or "").upper()
    if hvac_class == "AHU":
        return 1, 0, 0
    if hvac_class == "VAV":
        return 0, 1, 0
    if hvac_class == "ZONE":
        return 0, 0, 1
    pseudo = {
        "equipment_type": row.get("equipment_type") or row.get("type"),
        "brick_type": row.get("brick_type"),
        "name": row.get("name"),
    }
    if is_ahu(pseudo):
        return 1, 0, 0
    if is_vav(pseudo):
        return 0, 1, 0
    if is_zone(pseudo):
        return 0, 0, 1
    et = str(row.get("equipment_type") or row.get("type") or row.get("brick_type") or "").upper()
    name = str(row.get("name") or "").lower()
    if "AHU" in et or "RTU" in et or "ahu" in name or "rtu" in name:
        return 1, 0, 0
    if "VAV" in et or "vav" in name:
        return 0, 1, 0
    if "ZONE" in et:
        return 0, 0, 1
    return 0, 0, 0


def build_mechanical_narrative(site_id: str, *, fast: bool = False) -> dict[str, Any]:
    """Read-only narrative using Edge /api/model/fdd-query-presets/*."""
    site, token, client = edge_client_for_site(site_id)

    ahus = vavs = zones = 0
    point_rows = 0
    missing_bindings = 0
    orphan_points = 0
    coverage_lines: list[str] = []
    preset_errors: list[str] = []
    counts: dict[str, Any] = {}
    bacnet: dict[str, Any] = {}

    if fast:
        results, errors = run_parallel(
            {
                "hvac": lambda: _run_preset(client, "ahus_vavs_zones", token),
                "health": lambda: client.get_model_health(token=token),
                "bacnet": lambda: client.get_bacnet_poll_status(token=token),
            },
            max_workers=3,
        )
        for name, msg in errors.items():
            preset_errors.append(f"{name}: {msg}")
        hvac = results.get("hvac") or {}
        model_health = results.get("health") or {}
        bacnet = results.get("bacnet") or {}
        counts = model_health.get("counts") if isinstance(model_health.get("counts"), dict) else {}
        for row in hvac.get("rows") or []:
            if not isinstance(row, dict):
                continue
            da, dv, dz = _count_hvac_row(row)
            ahus += da
            vavs += dv
            zones += dz
        presets_used = list(_FAST_PRESETS)
    else:
        try:
            hvac = _run_preset(client, "ahus_vavs_zones", token)
            for row in hvac.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                da, dv, dz = _count_hvac_row(row)
                ahus += da
                vavs += dv
                zones += dz
        except RuntimeError as exc:
            preset_errors.append(f"ahus_vavs_zones: {exc}")

        try:
            eq_pts = _run_preset(client, "equipment_to_points", token)
            point_rows = int(eq_pts.get("row_count") or len(eq_pts.get("rows") or []))
        except RuntimeError as exc:
            preset_errors.append(f"equipment_to_points: {exc}")

        try:
            miss = _run_preset(client, "missing_rule_bindings", token)
            missing_bindings = int(miss.get("row_count") or len(miss.get("rows") or []))
        except RuntimeError as exc:
            preset_errors.append(f"missing_rule_bindings: {exc}")

        try:
            orphan = _run_preset(client, "orphan_points", token)
            orphan_points = int(orphan.get("row_count") or len(orphan.get("rows") or []))
        except RuntimeError as exc:
            preset_errors.append(f"orphan_points: {exc}")

        try:
            cov = _run_preset(client, "rule_coverage_by_equipment_type", token)
            for row in (cov.get("rows") or [])[:8]:
                if isinstance(row, dict):
                    et = row.get("equipment_type") or row.get("group")
                    cnt = row.get("rule_count") or row.get("count")
                    if et is not None and str(et) != "unknown":
                        coverage_lines.append(f"{et}: {cnt} rule(s)")
        except RuntimeError as exc:
            preset_errors.append(f"rule_coverage: {exc}")

        model_health = client.get_model_health(token=token)
        counts = model_health.get("counts") if isinstance(model_health.get("counts"), dict) else {}
        bacnet = client.get_bacnet_poll_status(token=token)
        presets_used = list(_NARRATIVE_PRESETS)

    zone_note = ""
    if zones == 0 and vavs > 0:
        zone_note = f" ({vavs} VAV terminal(s) — discrete HVAC_Zone equipment not modeled)"

    paragraphs = [
        f"{site.name} ({site_id}) at {site.base_url} — BRICK model via Edge FDD query presets "
        f"(same endpoints as the OpenFDD Edge Data Model tab).",
        (
            f"Mechanical inventory: {ahus} AHU(s), {vavs} VAV(s), {zones} zone(s){zone_note}; "
            + (
                f"{point_rows} equipment→point row(s) in the model graph."
                if not fast
                else "counts from ahus_vavs_zones preset (load full model for equipment→point detail)."
            )
        ),
        (
            f"Model health: {counts.get('equipment', '—')} equipment, {counts.get('points', '—')} points. "
            + (
                f"FDD coverage gaps: {missing_bindings} rule(s) with missing bindings, "
                f"{orphan_points} orphan/unused sensor point(s)."
                if not fast
                else "Use “Load FDD rules” or full preset buttons for binding coverage detail."
            )
        ),
    ]
    if coverage_lines:
        paragraphs.append("Rule coverage by equipment type: " + "; ".join(coverage_lines) + ".")
    if preset_errors:
        paragraphs.append("Preset warnings: " + "; ".join(preset_errors[:3]) + ".")
    if bacnet.get("last_poll_at"):
        paragraphs.append(
            f"BACnet poll: {bacnet.get('enabled_points', '—')} enabled point(s); "
            f"last poll {bacnet.get('last_poll_at')}."
        )

    return {
        "site_id": site_id,
        "narrative": "\n\n".join(paragraphs),
        "presets_used": presets_used,
        "fast_mode": fast,
        "counts": {
            "ahus": ahus,
            "vavs": vavs,
            "zones": zones,
            "equipment_point_rows": point_rows,
            "missing_rule_bindings": missing_bindings,
            "orphan_points": orphan_points,
        },
    }
