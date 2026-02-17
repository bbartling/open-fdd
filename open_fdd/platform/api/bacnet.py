"""BACnet proxy routes — Open-FDD backend calls diy-bacnet-server (local or OT LAN)."""

from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException

from open_fdd.platform.bacnet_brick import object_identifier_to_brick
from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn
from open_fdd.platform.data_model_ttl import (
    parse_bacnet_ttl_to_discovery,
    store_bacnet_scan_ttl,
    sync_ttl_to_file,
)
from open_fdd.platform.site_resolver import resolve_site_uuid

router = APIRouter(prefix="/bacnet", tags=["BACnet"])

_BASE_PAYLOAD = {"jsonrpc": "2.0", "id": "0"}


def _bacnet_url(body: dict) -> str:
    """Resolve BACnet gateway URL. When Open-FDD runs in Docker, omit url in body
    or pass localhost: we use OFDD_BACNET_SERVER_URL (e.g. host.docker.internal:8080)
    so the container can reach the gateway on the host."""
    url = (body.get("url") or "").strip().rstrip("/")
    server_url = (get_platform_settings().bacnet_server_url or "").strip().rstrip("/")
    if url and ("localhost" in url or "127.0.0.1" in url) and server_url:
        url = server_url
    elif not url:
        url = server_url or "http://localhost:8080"
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
def bacnet_server_hello(
    body: dict = Body(
        default={},
        examples={"default": {"value": {}}},
        description='Optional: {"url": "http://..."}. Omit to use server default (host.docker.internal:8080 in Docker).',
    )
):
    """
    Call diy-bacnet-server `server_hello`. Backend hits the BACnet gateway (same host or OT LAN).
    Omit url to use server default (when in Docker, server uses host.docker.internal:8080).
    """
    url = _bacnet_url(body or {})
    if not url.startswith("http"):
        return {"ok": False, "error": "Invalid URL"}
    result = _post_rpc(url, "server_hello", {}, timeout=5.0)
    return result


@router.post("/whois_range", summary="BACnet Who-Is range")
def bacnet_whois_range(
    body: dict = Body(
        default={},
        examples={
            "default": {
                "value": {"request": {"start_instance": 1, "end_instance": 3456799}}
            }
        },
        description="Optional url; request.start_instance and request.end_instance (0–4194303).",
    )
):
    """
    Call diy-bacnet-server `client_whois_range` to discover devices in an instance range.
    Omit url to use server default (host.docker.internal:8080 when Open-FDD runs in Docker).
    """
    url = _bacnet_url(body or {})
    if not url.startswith("http"):
        return {"ok": False, "error": "Invalid URL"}
    params = body or {}
    request = params.get("request") or {"start_instance": 1, "end_instance": 3456799}
    result = _post_rpc(url, "client_whois_range", {"request": request})
    return result


@router.post("/point_discovery", summary="BACnet point discovery")
def bacnet_point_discovery(
    body: dict = Body(
        default={},
        examples={"default": {"value": {"instance": {"device_instance": 3456789}}}},
        description="instance.device_instance (0–4194303). Optional url.",
    )
):
    """
    Call diy-bacnet-server `client_point_discovery` for a device instance.
    Omit url to use server default.
    """
    url = _bacnet_url(body or {})
    if not url.startswith("http"):
        return {"ok": False, "error": "Invalid URL"}
    params = body or {}
    instance = params.get("instance") or {"device_instance": 3456789}
    result = _post_rpc(url, "client_point_discovery", {"instance": instance})
    return result


@router.post("/discovery-to-rdf", summary="BACnet discovery to RDF (BRICK merge)")
def bacnet_discovery_to_rdf(
    body: dict = Body(
        default={},
        examples={
            "default": {
                "value": {
                    "request": {"start_instance": 3456789, "end_instance": 3456789},
                    "import_into_data_model": True,
                }
            }
        },
        description="request (start/end_instance). Set import_into_data_model: true to create site/equipment/points from the scan and sync config/brick_model.ttl. Omit url to use server default.",
    )
):
    """
    Call diy-bacnet-server `client_discovery_to_rdf`: Who-Is + deep scan, build RDF,
    return TTL and summary. Open-FDD stores the TTL and merges it for SPARQL.
    Set **import_into_data_model: true** to parse the TTL and create site/equipment/points
    in the DB (same as auto-import); config/brick_model.ttl is then synced from the DB.
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
    ttl_value = None
    try:
        res = result["body"]
        rpc_result = res.get("result") if isinstance(res, dict) else None
        ttl_value = rpc_result.get("ttl") if isinstance(rpc_result, dict) else None
        if isinstance(ttl_value, str) and ttl_value.strip():
            store_bacnet_scan_ttl(ttl_value)
    except Exception:
        pass
    # Auto-import: parse TTL → create site/equipment/points → sync brick_model.ttl
    if (
        params.get("import_into_data_model")
        and isinstance(ttl_value, str)
        and ttl_value.strip()
    ):
        try:
            site_id = (params.get("site_id") or "").strip() or None
            create_site = params.get("create_site", True)
            devices, point_discoveries = parse_bacnet_ttl_to_discovery(ttl_value)
            if point_discoveries:
                imp = _create_site_equipment_points_from_discovery(
                    site_id=site_id or "default",
                    create_site=create_site,
                    devices=devices,
                    point_discoveries=point_discoveries,
                )
                result["import_result"] = imp
                sync_ttl_to_file()
        except Exception as e:
            result["import_error"] = str(e)
    return result


def _create_site_equipment_points_from_discovery(
    site_id: str,
    create_site: bool,
    devices: list[dict],
    point_discoveries: list[dict],
) -> dict:
    """Create site/equipment/points from parsed discovery (devices + point_discoveries)."""
    device_names: dict[int, str] = {
        d["device_instance"]: (d.get("name") or f"BACnet device {d['device_instance']}")
        for d in devices
    }
    site_uuid = resolve_site_uuid(site_id, create_if_empty=create_site)
    if not site_uuid:
        raise HTTPException(400, "No site available and create_site is false")
    points_created = 0
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
    return {
        "status": "imported",
        "points_created": points_created,
        "site_id": str(site_uuid),
    }
