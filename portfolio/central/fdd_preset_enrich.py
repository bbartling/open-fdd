"""Enrich Edge FDD preset tables when model.json metadata is incomplete (GL36 BACnet sync)."""

from __future__ import annotations

from typing import Any

from portfolio.central.equipment_classify import effective_equipment_type, hvac_bucket, report_family
from portfolio.central.model_infer import infer_bacnet_device_id, infer_equipment_type, infer_object_identifier
from portfolio.collector.edge_client import EdgeClient


def enrich_fdd_preset(
    preset_id: str,
    data: dict[str, Any],
    *,
    client: EdgeClient,
    token: str,
) -> dict[str, Any]:
    """Post-process composed preset rows for RCx / Data Model tab display."""
    rows = data.get("rows")
    if not isinstance(rows, list):
        return data

    if preset_id == "points_by_bacnet_device":
        return _enrich_points_by_device(data, rows)
    if preset_id == "ahus_vavs_zones":
        return _enrich_ahus_vavs_zones(data, rows, client=client, token=token)
    if preset_id == "rules_to_equipment":
        return _enrich_rules_to_equipment(data, rows, client=client, token=token)
    if preset_id == "rules_to_bacnet_devices":
        return _enrich_rules_bacnet(data, rows, client=client, token=token)
    if preset_id == "rule_coverage_by_equipment_type":
        return _enrich_rule_coverage(data, rows, client=client, token=token)
    if preset_id == "equipment_to_points":
        return _enrich_equipment_to_points(data, rows, client=client, token=token)
    return data


def _equipment_map(client: EdgeClient, token: str) -> dict[str, dict[str, Any]]:
    try:
        tree = client.get_model_tree(token=token)
    except RuntimeError:
        return {}
    return {
        str(e.get("id") or e.get("equipment_id") or ""): e
        for e in (tree.get("equipment") or [])
        if isinstance(e, dict)
    }


def _enrich_points_by_device(data: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        dev = str(r.get("bacnet_device_id") or "")
        if dev in ("", "(none)"):
            pid = str(r.get("point_id") or "")
            fake_pt = {"id": pid}
            inferred = infer_bacnet_device_id(fake_pt)
            if inferred:
                r["bacnet_device_id"] = inferred
        out.append(r)
    cols = list(data.get("columns") or [])
    return {**data, "rows": out, "row_count": len(out), "columns": cols, "enriched": True}


def _enrich_ahus_vavs_zones(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    client: EdgeClient,
    token: str,
) -> dict[str, Any]:
    seen = {str(r.get("equipment_id") or "") for r in rows if isinstance(r, dict)}
    eq_map = _equipment_map(client, token)
    try:
        eq_pts = client.get_fdd_query_preset("equipment_to_points", token=token)
    except RuntimeError:
        eq_pts = {"rows": []}

    counts: dict[str, int] = {}
    for row in eq_pts.get("rows") or []:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("equipment_id") or "")
        counts[eid] = counts.get(eid, 0) + 1

    out = [dict(r) for r in rows if isinstance(r, dict)]
    for eid, count in sorted(counts.items()):
        if not eid or eid in seen:
            continue
        eq = eq_map.get(eid) or {"id": eid, "equipment_id": eid, "name": eid}
        bucket = hvac_bucket(eq)
        if not bucket:
            continue
        out.append(
            {
                "equipment_id": eid,
                "hvac_class": bucket,
                "equipment_type": infer_equipment_type(eq),
                "brick_type": str(eq.get("brick_type") or bucket),
                "name": str(eq.get("name") or eid),
                "point_count": count,
            }
        )
        seen.add(eid)

    for r in out:
        if not r.get("hvac_class"):
            eq = eq_map.get(str(r.get("equipment_id") or ""), {"id": r.get("equipment_id")})
            bucket = hvac_bucket(eq)
            if bucket:
                r["hvac_class"] = bucket
        if not r.get("equipment_type") or r.get("equipment_type") in ("—", "", "Equipment"):
            eq = eq_map.get(str(r.get("equipment_id") or ""), {})
            r["equipment_type"] = infer_equipment_type(eq) if eq else infer_equipment_type(
                {"id": r.get("equipment_id"), "name": r.get("name")}
            )

    cols = ["equipment_id", "hvac_class", "equipment_type", "brick_type", "name", "point_count"]
    out.sort(key=lambda r: (str(r.get("hvac_class") or ""), str(r.get("name") or "").lower()))
    return {**data, "rows": out, "row_count": len(out), "columns": cols, "enriched": True}


def _enrich_equipment_to_points(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    client: EdgeClient,
    token: str,
) -> dict[str, Any]:
    eq_map = _equipment_map(client, token)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        eq = eq_map.get(str(r.get("equipment_id") or ""), {})
        if not r.get("equipment_type") or r.get("equipment_type") in ("", "—"):
            r["equipment_type"] = infer_equipment_type(eq) if eq else ""
        out.append(r)
    return {**data, "rows": out, "row_count": len(out), "enriched": True}


def _enrich_rules_to_equipment(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    client: EdgeClient,
    token: str,
) -> dict[str, Any]:
    eq_map = _equipment_map(client, token)
    try:
        eq_pts = client.get_fdd_query_preset("equipment_to_points", token=token)
    except RuntimeError:
        eq_pts = {"rows": []}

    points_by_brick: dict[str, set[str]] = {}
    for row in eq_pts.get("rows") or []:
        if not isinstance(row, dict):
            continue
        bt = str(row.get("brick_class") or "")
        eid = str(row.get("equipment_id") or "")
        if bt and eid:
            points_by_brick.setdefault(bt, set()).add(eid)

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("equipment_id") or "").strip()
        brick_raw = str(row.get("brick_types") or "")
        bricks = [b.strip() for b in brick_raw.split(",") if b.strip()]
        if eid:
            eq = eq_map.get(eid, {})
            r = dict(row)
            if not r.get("equipment_type") or r.get("equipment_type") in ("—", ""):
                r["equipment_type"] = infer_equipment_type(eq) if eq else ""
            out.append(r)
            continue
        if bricks:
            matched: set[str] = set()
            for bt in bricks:
                matched.update(points_by_brick.get(bt, set()))
            if matched:
                for mid in sorted(matched):
                    eq = eq_map.get(mid, {"id": mid})
                    out.append(
                        {
                            **row,
                            "equipment_id": mid,
                            "equipment_type": infer_equipment_type(eq),
                            "brick_types": brick_raw,
                            "binding_inferred": True,
                        }
                    )
                continue
        out.append(dict(row))

    return {**data, "rows": out, "row_count": len(out), "enriched": True}


def _enrich_rules_bacnet(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    client: EdgeClient,
    token: str,
) -> dict[str, Any]:
    eq_map = _equipment_map(client, token)
    try:
        eq_pts = client.get_fdd_query_preset("equipment_to_points", token=token)
    except RuntimeError:
        eq_pts = {"rows": []}
    pt_index = {
        str(r.get("point_id") or ""): r
        for r in (eq_pts.get("rows") or [])
        if isinstance(r, dict)
    }

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        pid = str(r.get("point_id") or "")
        pt_row = pt_index.get(pid, {})
        eq = eq_map.get(str(pt_row.get("equipment_id") or ""), {})
        fake = {"id": pid, "equipment_id": pt_row.get("equipment_id")}
        dev = str(r.get("bacnet_device_id") or "").strip()
        if dev in ("", "—"):
            r["bacnet_device_id"] = infer_bacnet_device_id(fake, equipment=eq)
        obj = str(r.get("object_identifier") or "").strip()
        if obj in ("", "—"):
            r["object_identifier"] = infer_object_identifier({"id": pid, "bacnet_object": pt_row.get("bacnet_object")})
        out.append(r)
    return {**data, "rows": out, "row_count": len(out), "enriched": True}


def _enrich_rule_coverage(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    client: EdgeClient,
    token: str,
) -> dict[str, Any]:
    try:
        rules_raw = client.get_fdd_query_preset("rules_to_equipment", token=token)
    except RuntimeError:
        return data
    enriched_rules = _enrich_rules_to_equipment(
        rules_raw,
        rules_raw.get("rows") or [],
        client=client,
        token=token,
    )
    tally: dict[str, list[str]] = {}
    for row in enriched_rules.get("rows") or []:
        if not isinstance(row, dict):
            continue
        et = str(row.get("equipment_type") or "").strip()
        if not et or et in ("unknown", "Equipment", "—"):
            fam = report_family({"equipment_id": row.get("equipment_id"), "name": row.get("equipment_id")})
            et = {"ahu": "AHU", "vav": "VAV", "hws": "Hot_Water_Plant"}.get(fam, "BRICK-bound")
        rid = str(row.get("rule_id") or "")
        if rid and rid not in tally.get(et, []):
            tally.setdefault(et, []).append(rid)
    if not tally:
        return data
    out = [
        {"equipment_type": et, "rule_count": len(rids), "rule_ids": ", ".join(rids)}
        for et, rids in sorted(tally.items())
    ]
    return {**data, "rows": out, "row_count": len(out), "enriched": True}
