"""BACnet proxy routes — Open-FDD backend calls diy-bacnet-server (local or OT LAN)."""

import httpx
from fastapi import APIRouter, Body, HTTPException

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.graph_model import (
    update_bacnet_from_point_discovery,
    write_ttl_to_file as graph_write_ttl,
)

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


@router.post(
    "/point_discovery_to_graph", summary="BACnet point discovery → in-memory graph"
)
def bacnet_point_discovery_to_graph(
    body: dict = Body(
        default={},
        examples={
            "default": {
                "value": {
                    "instance": {"device_instance": 3456789},
                    "update_graph": True,
                    "write_file": True,
                }
            }
        },
        description="instance.device_instance. Set update_graph=true to update in-memory graph with clean BACnet RDF (no bacpypes repr). write_file=true to serialize to brick_model.ttl.",
    )
):
    """
    Call point_discovery, then update the in-memory graph with clean BACnet TTL from the JSON.
    Puts clean BACnet RDF into the in-memory graph and optionally writes config/brick_model.ttl.
    """
    url = _bacnet_url(body or {})
    if not url.startswith("http"):
        return {"ok": False, "error": "Invalid URL"}
    params = body or {}
    instance = params.get("instance") or {"device_instance": 3456789}
    dev_inst = instance.get("device_instance")
    result = _post_rpc(url, "client_point_discovery", {"instance": instance})
    if not result.get("ok") or not result.get("body"):
        return result
    if not params.get("update_graph"):
        return result
    try:
        res = result["body"]
        rpc_result = res.get("result") if isinstance(res, dict) else None
        data = (
            (rpc_result.get("data") or rpc_result)
            if isinstance(rpc_result, dict)
            else {}
        )
        objs = data.get("objects") or []
        addr = data.get("device_address") or ""
        dev_name = None
        for o in objs:
            if isinstance(o, dict) and (o.get("object_identifier") or "").startswith(
                "device,"
            ):
                dev_name = o.get("object_name") or o.get("name")
                break
        update_bacnet_from_point_discovery(
            dev_inst,
            addr,
            objs,
            device_name=dev_name,
        )
        if params.get("write_file", True):
            graph_write_ttl()
    except Exception as e:
        result["graph_error"] = str(e)
    return result
