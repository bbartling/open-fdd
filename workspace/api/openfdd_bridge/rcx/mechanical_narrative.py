"""Paragraph mechanical summary from local FDD query presets."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from ..equipment_classify import is_ahu, is_vav, is_zone
from ..fdd_query_presets import run_fdd_preset
from ..dashboard_analytics import build_model_health
from ..model_service import ModelService
from ..site_defaults import default_site_id, ensure_default_site
from ..ttl_service import TtlService

_NARRATIVE_PRESETS = (
    "ahus_vavs_zones",
    "equipment_to_points",
    "missing_rule_bindings",
    "orphan_points",
    "rule_coverage_by_equipment_type",
)

_FAST_PRESETS = ("ahus_vavs_zones",)


def _run_parallel(
    tasks: dict[str, Callable[[], Any]],
    *,
    max_workers: int = 4,
) -> tuple[dict[str, Any], dict[str, str]]:
    if not tasks:
        return {}, {}
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    workers = min(max_workers, len(tasks))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as exc:
                errors[name] = str(exc)[:300]
    return results, errors


def _resolve_site_id(site_id: str) -> str:
    sid = str(site_id or "").strip()
    if sid:
        return sid
    svc = ModelService()
    return ensure_default_site(svc, TtlService()) or default_site_id()


def _site_name(site_id: str) -> str:
    try:
        model = ModelService().load()
        for site in model.get("sites") or []:
            if isinstance(site, dict) and str(site.get("id") or "") == site_id:
                return str(site.get("name") or site_id)
    except Exception:
        pass
    return site_id


def _count_hvac_row(row: dict[str, Any]) -> tuple[int, int, int]:
    hvac_class = str(row.get("hvac_class") or "").upper()
    if hvac_class == "AHU":
        return 1, 0, 0
    if hvac_class == "VAV":
        return 0, 1, 0
    if hvac_class == "ZONE":
        return 0, 0, 1
    pseudo = {
        "id": row.get("equipment_id"),
        "equipment_id": row.get("equipment_id"),
        "equipment_type": row.get("equipment_type") or row.get("type"),
        "brick_type": row.get("brick_type"),
        "name": row.get("name") or row.get("equipment_id"),
        "bacnet_device_instance": row.get("bacnet_device_instance"),
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


def _supplement_hvac_counts(
    *,
    site_id: str,
    seen: set[str],
    ahus: int,
    vavs: int,
    zones: int,
) -> tuple[int, int, int]:
    try:
        eq_pts = run_fdd_preset("equipment_to_points", site_id=site_id)
    except KeyError:
        return ahus, vavs, zones
    for row in eq_pts.get("rows") or []:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("equipment_id") or "").strip()
        if not eid or eid in seen:
            continue
        pseudo = {
            "id": eid,
            "equipment_id": eid,
            "name": eid,
            "equipment_type": row.get("equipment_type"),
            "brick_type": row.get("brick_type"),
        }
        da, dv, dz = _count_hvac_row(pseudo)
        if not (da or dv or dz):
            continue
        seen.add(eid)
        ahus += da
        vavs += dv
        zones += dz
    return ahus, vavs, zones


def build_mechanical_narrative(site_id: str, *, fast: bool = False) -> dict[str, Any]:
    """Read-only narrative using local FDD query presets."""
    sid = _resolve_site_id(site_id)
    site_name = _site_name(sid)

    ahus = vavs = zones = 0
    point_rows = 0
    missing_bindings = 0
    orphan_points = 0
    coverage_lines: list[str] = []
    preset_errors: list[str] = []
    counts: dict[str, Any] = {}
    bacnet: dict[str, Any] = {}

    if fast:
        results, errors = _run_parallel(
            {
                "hvac": lambda: run_fdd_preset("ahus_vavs_zones", site_id=sid),
                "health": lambda: build_model_health(),
                "bacnet": lambda: _bacnet_status(),
            },
            max_workers=3,
        )
        preset_errors.extend(f"{k}: {v}" for k, v in errors.items())
        hvac = results.get("hvac") or {}
        model_health = results.get("health") or {}
        bacnet = results.get("bacnet") or {}
        counts = model_health.get("counts") if isinstance(model_health.get("counts"), dict) else {}
        seen_hvac: set[str] = set()
        for row in hvac.get("rows") or []:
            if not isinstance(row, dict):
                continue
            eid = str(row.get("equipment_id") or "").strip()
            if eid:
                seen_hvac.add(eid)
            da, dv, dz = _count_hvac_row(row)
            ahus += da
            vavs += dv
            zones += dz
        ahus, vavs, zones = _supplement_hvac_counts(
            site_id=sid, seen=seen_hvac, ahus=ahus, vavs=vavs, zones=zones
        )
        presets_used = list(_FAST_PRESETS)
    else:
        try:
            hvac = run_fdd_preset("ahus_vavs_zones", site_id=sid)
            seen_hvac: set[str] = set()
            for row in hvac.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                eid = str(row.get("equipment_id") or "").strip()
                if eid:
                    seen_hvac.add(eid)
                da, dv, dz = _count_hvac_row(row)
                ahus += da
                vavs += dv
                zones += dz
            ahus, vavs, zones = _supplement_hvac_counts(
                site_id=sid, seen=seen_hvac, ahus=ahus, vavs=vavs, zones=zones
            )
        except KeyError as exc:
            preset_errors.append(f"ahus_vavs_zones: {exc}")

        for preset_id, assign in (
            ("equipment_to_points", lambda r: int(r.get("row_count") or len(r.get("rows") or []))),
            ("missing_rule_bindings", lambda r: int(r.get("row_count") or len(r.get("rows") or []))),
            ("orphan_points", lambda r: int(r.get("row_count") or len(r.get("rows") or []))),
        ):
            try:
                raw = run_fdd_preset(preset_id, site_id=sid)
                val = assign(raw)
                if preset_id == "equipment_to_points":
                    point_rows = val
                elif preset_id == "missing_rule_bindings":
                    missing_bindings = val
                else:
                    orphan_points = val
            except KeyError as exc:
                preset_errors.append(f"{preset_id}: {exc}")

        try:
            cov = run_fdd_preset("rule_coverage_by_equipment_type", site_id=sid)
            for row in (cov.get("rows") or [])[:8]:
                if isinstance(row, dict):
                    et = row.get("equipment_type") or row.get("group")
                    cnt = row.get("rule_count") or row.get("count")
                    if et is not None and str(et) != "unknown":
                        coverage_lines.append(f"{et}: {cnt} rule(s)")
        except KeyError as exc:
            preset_errors.append(f"rule_coverage: {exc}")

        model_health = build_model_health()
        counts = model_health.get("counts") if isinstance(model_health.get("counts"), dict) else {}
        bacnet = _bacnet_status()
        presets_used = list(_NARRATIVE_PRESETS)

    zone_note = ""
    if zones == 0 and vavs > 0:
        zone_note = f" ({vavs} VAV terminal(s) — discrete HVAC_Zone equipment not modeled)"

    paragraphs = [
        f"{site_name} ({sid}) — local OpenFDD Edge BRICK model via FDD query presets "
        "(same endpoints as the Data Model tab).",
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
        "site_id": sid,
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


def _bacnet_status() -> dict[str, Any]:
    try:
        from ..poll_throughput import compute_poll_throughput

        pt = compute_poll_throughput(window_minutes=60)
        return {
            "enabled_points": pt.get("enabled_points"),
            "last_poll_at": pt.get("last_poll_at"),
        }
    except Exception:
        return {}
