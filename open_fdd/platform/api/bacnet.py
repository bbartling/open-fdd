"""BACnet proxy routes — Open-FDD backend calls diy-bacnet-server (local or OT LAN)."""

from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException

from open_fdd.platform.bacnet_brick import object_identifier_to_brick
from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn
from open_fdd.platform.data_model_ttl import sync_ttl_to_file, store_bacnet_scan_ttl
from open_fdd.platform.site_resolver import resolve_site_uuid

router = APIRouter(prefix="/bacnet", tags=["BACnet"])

_BASE_PAYLOAD = {"jsonrpc": "2.0", "id": "0"}


def _bacnet_url(body: dict) -> str:
    url = (body.get("url") or "").strip().rstrip("/")
    if not url:
        url = (get_platform_settings().bacnet_server_url or "").strip().rstrip("/")
    if not url:
        url = "http://localhost:8080"
    return url


def _post_rpc(base_url: str, method: str, params: dict, timeout: float = 10.0) -> dict:
    """POST JSON-RPC to diy-bacnet-server; return full response or error."""
    url = base_url.rstrip("/") + "/" + method
    payload = {**_BASE_PAYLOAD, "method": method, "params": params}
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
        out = {"ok": r.is_success, "status_code": r.status_code}
        try:
            out["body"] = r.json()
        except Exception:
            out["text"] = r.text
        if not r.is_success:
            out["error"] = r.text or f"HTTP {r.status_code}"
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/server_hello", summary="BACnet server hello")
def bacnet_server_hello(body: dict = Body(default={})):
    """
    Call diy-bacnet-server `server_hello`. Backend hits the BACnet gateway (same host or OT LAN).
    Body: `{"url": "http://localhost:8080"}` (optional; uses OFDD_BACNET_SERVER_URL or localhost:8080).
    """
    url = _bacnet_url(body or {})
    if not url.startswith("http"):
        return {"ok": False, "error": "Invalid URL"}
    result = _post_rpc(url, "server_hello", {}, timeout=5.0)
    return result


@router.post("/whois_range", summary="BACnet Who-Is range")
def bacnet_whois_range(body: dict = Body(default={})):
    """
    Call diy-bacnet-server `client_whois_range` to discover devices in an instance range.
    Body: `{"url": "http://...", "request": {"start_instance": 1, "end_instance": 3456799}}`.
    """
    url = _bacnet_url(body or {})
    if not url.startswith("http"):
        return {"ok": False, "error": "Invalid URL"}
    params = body or {}
    request = params.get("request") or {"start_instance": 1, "end_instance": 3456799}
    result = _post_rpc(url, "client_whois_range", {"request": request})
    return result


@router.post("/point_discovery", summary="BACnet point discovery")
def bacnet_point_discovery(body: dict = Body(default={})):
    """
    Call diy-bacnet-server `client_point_discovery` for a device instance.
    Body: `{"url": "http://...", "instance": {"device_instance": 3456789}}`.
    """
    url = _bacnet_url(body or {})
    if not url.startswith("http"):
        return {"ok": False, "error": "Invalid URL"}
    params = body or {}
    instance = params.get("instance") or {"device_instance": 3456789}
    result = _post_rpc(url, "client_point_discovery", {"instance": instance})
    return result


@router.post("/discovery-to-rdf", summary="BACnet discovery to RDF (BRICK merge)")
def bacnet_discovery_to_rdf(body: dict = Body(default={})):
    """
    Call diy-bacnet-server `client_discovery_to_rdf`: Who-Is + deep scan, build RDF
    with BACnetGraph, return TTL and summary. Open-FDD stores the TTL and merges it
    into the SPARQL graph so CRUD + BACnet topology stay in sync.
    Body: `{"url": "http://...", "request": {"start_instance": 1, "end_instance": 3456799}}`.
    """
    url = _bacnet_url(body or {})
    if not url.startswith("http"):
        return {"ok": False, "error": "Invalid URL"}
    params = body or {}
    request = params.get("request") or {"start_instance": 1, "end_instance": 3456799}
    result = _post_rpc(
        url, "client_discovery_to_rdf", {"request": request}, timeout=120.0
    )
    if not result.get("ok") or not result.get("body"):
        return result
    # Success: store TTL so SPARQL sees merged graph (DB + BACnet)
    try:
        res = result["body"]
        rpc_result = res.get("result") if isinstance(res, dict) else None
        ttl_value = rpc_result.get("ttl") if isinstance(rpc_result, dict) else None
        if isinstance(ttl_value, str) and ttl_value.strip():
            store_bacnet_scan_ttl(ttl_value)
    except Exception:
        pass  # still return the RPC response
    return result


def _normalize_import_body(body: dict) -> tuple[list[dict], list[dict]]:
    """
    Extract (devices, point_discoveries) from import-discovery body.
    Accepts normalized form or raw API response shapes.
    - devices: [ { device_instance, name? } ]
    - point_discoveries: [ { device_instance, objects: [ { object_identifier, object_name?, object_type? } ] } ]
    """
    devices: list[dict] = []
    point_discoveries: list[dict] = []

    if body.get("devices") and isinstance(body["devices"], list):
        for d in body["devices"]:
            if isinstance(d, dict) and d.get("device_instance") is not None:
                devices.append(
                    {
                        "device_instance": int(d["device_instance"]),
                        "name": (d.get("name") or d.get("object_name") or "").strip()
                        or None,
                    }
                )
    elif body.get("whois_result") and isinstance(body["whois_result"], dict):
        # Raw whois API response: body.result.data or body.result
        res = body["whois_result"].get("body") or body["whois_result"]
        data = res.get("result") or {}
        if isinstance(data, dict):
            data = data.get("data") or data.get("devices") or []
        if isinstance(data, list):
            for d in data:
                if isinstance(d, dict) and d.get("device_instance") is not None:
                    devices.append(
                        {
                            "device_instance": int(d["device_instance"]),
                            "name": (
                                d.get("name") or d.get("object_name") or ""
                            ).strip()
                            or None,
                        }
                    )

    if body.get("point_discoveries") and isinstance(body["point_discoveries"], list):
        for pd in body["point_discoveries"]:
            if isinstance(pd, dict) and pd.get("device_instance") is not None:
                objs = pd.get("objects") or pd.get("results") or []
                if not isinstance(objs, list):
                    objs = []
                point_discoveries.append(
                    {
                        "device_instance": int(pd["device_instance"]),
                        "objects": [
                            {
                                "object_identifier": (
                                    o.get("object_identifier")
                                    or o.get("object_id")
                                    or ""
                                ).strip(),
                                "object_name": (
                                    o.get("object_name") or o.get("name") or ""
                                ).strip()
                                or None,
                                "object_type": (o.get("object_type") or "").strip()
                                or None,
                            }
                            for o in objs
                            if isinstance(o, dict)
                            and (o.get("object_identifier") or o.get("object_id"))
                        ],
                    }
                )
    elif body.get("point_discovery_result") and isinstance(
        body["point_discovery_result"], dict
    ):
        import json as _json

        raw = (
            body["point_discovery_result"].get("body") or body["point_discovery_result"]
        )
        res = raw
        if isinstance(raw, str):
            try:
                res = _json.loads(raw)
            except Exception:
                res = {}
        if not isinstance(res, dict):
            res = {}
        # Support both JSON-RPC wrapped (res.result) and raw BaseResponse (res = result)
        result = res.get("result")
        if result is None and ("data" in res or "success" in res):
            result = res
        result = result if isinstance(result, dict) else {}
        inner = result.get("data") or {}
        if not isinstance(inner, dict):
            inner = {}
        di = (
            result.get("device_instance")
            or inner.get("device_instance")
            or body.get("device_instance")
            or body.get("deviceInstance")
        )
        objs = (
            result.get("objects") or inner.get("objects") or result.get("results") or []
        )
        if not isinstance(objs, list):
            objs = []
        if di is not None:
            point_discoveries.append(
                {
                    "device_instance": int(di),
                    "objects": [
                        {
                            "object_identifier": (
                                o.get("object_identifier") or o.get("object_id") or ""
                            ).strip(),
                            "object_name": (
                                o.get("object_name") or o.get("name") or ""
                            ).strip()
                            or None,
                            "object_type": (o.get("object_type") or "").strip() or None,
                        }
                        for o in objs
                        if isinstance(o, dict)
                        and (o.get("object_identifier") or o.get("object_id"))
                    ],
                }
            )
        # Unconditional fallback: body has device_instance but we parsed nothing
        if not point_discoveries and (
            body.get("device_instance") is not None
            or body.get("deviceInstance") is not None
        ):
            di_fallback = body.get("device_instance") or body.get("deviceInstance")
            point_discoveries.append(
                {"device_instance": int(di_fallback), "objects": []}
            )

    # Top-level fallback: client sent device_instance (with or without point_discovery_result)
    if not point_discoveries and (
        body.get("device_instance") is not None
        or body.get("deviceInstance") is not None
    ):
        di_any = body.get("device_instance") or body.get("deviceInstance")
        point_discoveries.append({"device_instance": int(di_any), "objects": []})

    return devices, point_discoveries


@router.post("/import-discovery", summary="Import BACnet discovery into data model")
def bacnet_import_discovery(body: dict = Body(default={})):
    """
    Create site/equipment/points from Who-Is and point-discovery results.
    Body: site_id (optional), create_site (optional), devices (optional), point_discoveries (required for points),
    or whois_result / point_discovery_result (raw API response shapes).
    Creates one equipment per device (e.g. "BACnet device 3456789"), then points with BACnet addressing and BRICK type.
    """
    site_id = (body.get("site_id") or "").strip() or None
    create_site = body.get("create_site", True)
    devices, point_discoveries = _normalize_import_body(body or {})

    device_names: dict[int, str] = {
        d["device_instance"]: (d["name"] or f"BACnet device {d['device_instance']}")
        for d in devices
    }

    if not point_discoveries:
        raise HTTPException(
            422,
            "Provide point_discoveries (or point_discovery_result) with device_instance and objects",
        )

    site_uuid = resolve_site_uuid(site_id or "default", create_if_empty=create_site)
    if not site_uuid:
        raise HTTPException(400, "No site available and create_site is false")

    with get_conn() as conn:
        with conn.cursor() as cur:
            equipment_by_device: dict[int, Any] = {}
            for pd in point_discoveries:
                di = pd["device_instance"]
                if di in equipment_by_device:
                    continue
                name = device_names.get(di) or f"BACnet device {di}"
                cur.execute(
                    "SELECT id FROM equipment WHERE site_id = %s AND name = %s",
                    (str(site_uuid), name),
                )
                row = cur.fetchone()
                if row:
                    equipment_by_device[di] = row["id"]
                else:
                    cur.execute(
                        """INSERT INTO equipment (site_id, name, equipment_type)
                           VALUES (%s, %s, 'BACnet')
                           RETURNING id""",
                        (str(site_uuid), name),
                    )
                    equipment_by_device[di] = cur.fetchone()["id"]

            points_created = 0
            for pd in point_discoveries:
                eq_id = equipment_by_device.get(pd["device_instance"])
                for o in pd.get("objects") or []:
                    oid = (o.get("object_identifier") or "").strip()
                    if not oid:
                        continue
                    obj_name = (o.get("object_name") or oid.replace(",", "_")).strip()
                    external_id = obj_name or oid.replace(",", "_")
                    brick_type = object_identifier_to_brick(
                        oid
                    ) or object_identifier_to_brick(o.get("object_type"))
                    cur.execute(
                        """INSERT INTO points (site_id, external_id, bacnet_device_id, object_identifier, object_name, brick_type, equipment_id)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (site_id, external_id) DO UPDATE SET
                             bacnet_device_id = EXCLUDED.bacnet_device_id,
                             object_identifier = EXCLUDED.object_identifier,
                             object_name = EXCLUDED.object_name,
                             brick_type = COALESCE(EXCLUDED.brick_type, points.brick_type),
                             equipment_id = COALESCE(EXCLUDED.equipment_id, points.equipment_id)
                           """,
                        (
                            str(site_uuid),
                            external_id,
                            str(pd["device_instance"]),
                            oid,
                            obj_name,
                            brick_type,
                            eq_id,
                        ),
                    )
                    points_created += 1
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return {
        "status": "imported",
        "points_created": points_created,
        "site_id": str(site_uuid),
    }
