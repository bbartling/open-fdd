"""Programmatic BRICK model fixes on Edge (integrator auth)."""

from __future__ import annotations

from typing import Any

from portfolio.central.edge_registry import resolve_site_config, resolve_token
from portfolio.central.equipment_classify import hvac_bucket, is_ahu, is_vav, report_family
from portfolio.central.model_infer import enrich_point_row, infer_bacnet_device_id, infer_equipment_type
from portfolio.collector.edge_client import EdgeClient, api_patch, api_post

# Canonical Acme roof RTU — packaged AHU feeding VAV terminals.
_ACME_RTU_PATCHES: list[dict[str, Any]] = [
    {
        "match_id": "acme-vm-bbartling-rtu-01",
        "patch": {
            "name": "AHU 01",
            "equipment_type": "AHU",
            "brick_type": "AHU",
            "bacnet_device_instance": 1100,
        },
    },
]


def _infer_rtu_patches(model: dict[str, Any]) -> list[dict[str, Any]]:
    """Find untyped RTU/AHU equipment rows that need brick_type for SPARQL + presets."""
    patches: list[dict[str, Any]] = []
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        eid = str(eq.get("id") or "")
        if not eid:
            continue
        bucket = hvac_bucket(eq)
        if bucket == "AHU" and str(eq.get("brick_type") or "").upper() in ("", "EQUIPMENT", "RTU"):
            patches.append(
                {
                    "equipment_id": eid,
                    "patch": {
                        "name": eq.get("name") or "AHU 01",
                        "equipment_type": "AHU",
                        "brick_type": "AHU",
                    },
                }
            )
            continue
        if bucket:
            continue
        eid_l = eid.lower()
        if "-rtu-" not in eid_l and not eid_l.endswith("-rtu"):
            continue
        patches.append(
            {
                "equipment_id": eid,
                "patch": {
                    "name": eq.get("name") or "AHU 01",
                    "equipment_type": "AHU",
                    "brick_type": "AHU",
                },
            }
        )
    return patches


def remediate_hvac_equipment(site_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Tag roof RTU / untyped AHU rows on Edge model.json and sync TTL."""
    site = resolve_site_config(site_id)
    token = resolve_token(site)
    client = EdgeClient(site.base_url)

    model = client.api_get("/api/model/export", token=token)
    planned: list[dict[str, Any]] = []

    for spec in _ACME_RTU_PATCHES:
        eid = spec["match_id"]
        eq = next((e for e in (model.get("equipment") or []) if str(e.get("id")) == eid), None)
        if eq is None:
            continue
        if is_ahu(eq) and str(eq.get("brick_type") or "").upper() == "AHU":
            continue
        planned.append({"equipment_id": eid, "patch": spec["patch"], "reason": "canonical acme RTU"})

    for item in _infer_rtu_patches(model):
        eid = item["equipment_id"]
        if any(p["equipment_id"] == eid for p in planned):
            continue
        planned.append({**item, "reason": "inferred from equipment id / points"})

    if dry_run:
        return {"site_id": site_id, "dry_run": True, "planned": planned, "applied": []}

    applied: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in planned:
        eid = item["equipment_id"]
        body = item["patch"]
        try:
            out = api_patch(client.base_url, token, f"/api/model/equipment/{eid}", body)
            applied.append({"equipment_id": eid, "equipment": out.get("equipment"), "patch": body})
        except RuntimeError as exc:
            if "HTTP 404" in str(exc) or "HTTP 405" in str(exc):
                # Older Edge: merge via full import
                try:
                    _apply_via_import(client, token, model, eid, body)
                    applied.append({"equipment_id": eid, "patch": body, "via": "import"})
                except RuntimeError as imp_exc:
                    errors.append(f"{eid}: {imp_exc}")
            else:
                errors.append(f"{eid}: {exc}")

    return {
        "site_id": site_id,
        "dry_run": False,
        "planned": planned,
        "applied": applied,
        "errors": errors,
    }


def _apply_via_import(
    client: EdgeClient,
    token: str,
    model: dict[str, Any],
    equipment_id: str,
    patch: dict[str, Any],
) -> None:
    for eq in model.get("equipment") or []:
        if isinstance(eq, dict) and str(eq.get("id") or "") == equipment_id:
            eq.update(patch)
            break
    else:
        raise RuntimeError(f"equipment not found in export: {equipment_id}")
    api_post(client.base_url, token, "/api/model/import", {"payload": model, "replace": True})


def remediate_full_model(site_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Fix equipment types, BACnet device ids on points, and sync TTL on Edge."""
    site = resolve_site_config(site_id)
    token = resolve_token(site)
    client = EdgeClient(site.base_url)
    model = client.api_get("/api/model/export", token=token)

    eq_index = {
        str(e.get("id") or ""): e
        for e in (model.get("equipment") or [])
        if isinstance(e, dict) and e.get("id")
    }
    equipment_patches = 0
    point_patches = 0

    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        eid = str(eq.get("id") or "")
        fam = report_family(eq)
        if fam == "ahu" and str(eq.get("brick_type") or "").upper() != "AHU":
            eq["brick_type"] = "AHU"
            eq["equipment_type"] = "AHU"
            if "rtu" in eid.lower() and not str(eq.get("name") or "").lower().startswith("ahu"):
                eq["name"] = "AHU 01"
            equipment_patches += 1
        elif fam == "vav" and not str(eq.get("brick_type") or "").upper().startswith("VAV"):
            eq["brick_type"] = "VAV"
            eq["equipment_type"] = "VAV"
            equipment_patches += 1
        elif fam == "hws" and "HOT_WATER" not in str(eq.get("brick_type") or "").upper():
            eq["brick_type"] = "Hot_Water_Plant"
            eq["equipment_type"] = "Hot_Water_Plant"
            equipment_patches += 1

    for raw in model.get("points") or []:
        if not isinstance(raw, dict):
            continue
        eq = eq_index.get(str(raw.get("equipment_id") or ""), {})
        before_dev = infer_bacnet_device_id(raw, equipment=eq)
        pt = enrich_point_row(raw, equipment=eq)
        after_dev = infer_bacnet_device_id(pt, equipment=eq)
        if after_dev and after_dev != before_dev:
            point_patches += 1
        raw.clear()
        raw.update(pt)

    summary = {
        "site_id": site_id,
        "dry_run": dry_run,
        "equipment_patches": equipment_patches,
        "point_bacnet_patches": point_patches,
        "equipment_count": len(model.get("equipment") or []),
        "point_count": len(model.get("points") or []),
    }
    if dry_run:
        return summary

    api_post(client.base_url, token, "/api/model/import", {"payload": model, "replace": True})
    try:
        client.api_post("/api/model/sync-ttl", {}, token=token)
        summary["ttl_synced"] = True
    except RuntimeError as exc:
        summary["ttl_synced"] = False
        summary["ttl_error"] = str(exc)[:200]
    try:
        from portfolio.central.model_ttl_mirror import mirror_site_ttl

        summary["ttl_mirror"] = mirror_site_ttl(site_id, sync_edge=False)
    except RuntimeError as exc:
        summary["ttl_mirror_error"] = str(exc)[:200]
    return summary
