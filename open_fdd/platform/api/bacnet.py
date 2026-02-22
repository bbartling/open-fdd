"""BACnet proxy routes — Open-FDD backend calls diy-bacnet-server (local or OT LAN)."""

import json
import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.graph_model import (
    get_ttl_path_resolved,
    update_bacnet_from_point_discovery,
    write_ttl_to_file as graph_write_ttl,
)

router = APIRouter(prefix="/bacnet", tags=["BACnet"])

_BASE_PAYLOAD = {"jsonrpc": "2.0", "id": "0"}


def _effective_bacnet_server_url() -> str:
    """URL for the default BACnet gateway. Prefer env OFDD_BACNET_SERVER_URL over graph overlay so Docker (host.docker.internal) works when Swagger omits url."""
    env_url = (os.environ.get("OFDD_BACNET_SERVER_URL") or "").strip().rstrip("/")
    if env_url:
        return env_url
    s = get_platform_settings()
    return (s.bacnet_server_url or "http://localhost:8080").strip().rstrip("/")


def _get_gateways_list() -> list[dict]:
    """Return list of {id, url, site_id?} from config (default + bacnet_gateways). Used for GET /bacnet/gateways and gateway resolution."""
    s = get_platform_settings()
    default_url = _effective_bacnet_server_url()
    out = [{"id": "default", "url": default_url, "description": "Config default (OFDD_BACNET_SERVER_URL)"}]
    if s.bacnet_gateways:
        try:
            gw = json.loads(s.bacnet_gateways)
            if isinstance(gw, list):
                for i, g in enumerate(gw):
                    if isinstance(g, dict) and g.get("url"):
                        out.append({
                            "id": str(i),
                            "url": str(g["url"]).strip().rstrip("/"),
                            "site_id": g.get("site_id"),
                            "description": f"Gateway {i} ({g.get('site_id', '')})",
                        })
        except (json.JSONDecodeError, TypeError):
            pass
    return out


def _resolve_gateway_url(gateway_id: str | None) -> str | None:
    """Resolve gateway id (e.g. 'default', '0') to URL. Returns None if not found or gateway_id is None."""
    if not gateway_id:
        return None
    for g in _get_gateways_list():
        if g["id"] == gateway_id:
            return g["url"]
    return None


def _gateway_enum() -> list[str]:
    """Gateway ids for Swagger dropdown (built at import so enum is stable)."""
    return [g["id"] for g in _get_gateways_list()]


# --- Request body models (Swagger schema + examples) ---


class WhoIsRequestRange(BaseModel):
    """Instance range for BACnet Who-Is (0–4194303)."""

    start_instance: int = Field(
        default=1,
        ge=0,
        le=4194303,
        description="Start device instance",
    )
    end_instance: int = Field(
        default=3456799,
        ge=0,
        le=4194303,
        description="End device instance",
    )


class WhoIsBody(BaseModel):
    """Body for POST /bacnet/whois_range. Matches diy-bacnet-server client_whois_range."""

    url: str | None = Field(
        default=None,
        examples=[None],
        description="Gateway URL; omit to use server default (or use ?gateway= from GET /bacnet/gateways)",
    )
    request: WhoIsRequestRange | None = Field(
        default_factory=lambda: WhoIsRequestRange(),
        description="Instance range for Who-Is",
    )


WHOIS_EXAMPLES = {
    "default": {
        "summary": "Default range (1–3.4M); change start/end as needed",
        "value": {"url": None, "request": {"start_instance": 1, "end_instance": 3456799}},
    },
    "low": {
        "summary": "Low instance IDs (1–999)",
        "value": {"url": None, "request": {"start_instance": 1, "end_instance": 999}},
    },
    "high": {
        "summary": "Full BACnet range (1–4194303)",
        "value": {"url": None, "request": {"start_instance": 1, "end_instance": 4194303}},
    },
}


class PointDiscoveryInstance(BaseModel):
    """Device instance for point discovery (0–4194303)."""

    device_instance: int = Field(
        default=3456789,
        ge=0,
        le=4194303,
        description="BACnet device instance number",
    )


class PointDiscoveryBody(BaseModel):
    """Body for POST /bacnet/point_discovery. Matches diy-bacnet-server client_point_discovery."""

    url: str | None = Field(
        default=None,
        examples=[None],
        description="Gateway URL; omit to use server default (or use ?gateway= from GET /bacnet/gateways)",
    )
    instance: PointDiscoveryInstance | None = Field(
        default_factory=lambda: PointDiscoveryInstance(),
        description="Device to discover; change device_instance only",
    )


POINT_DISCOVERY_EXAMPLES = {
    "default": {
        "summary": "Change device_instance only; returns object list",
        "value": {"url": None, "instance": {"device_instance": 3456789}},
    },
    "device_1234": {
        "summary": "Device instance 1234",
        "value": {"url": None, "instance": {"device_instance": 1234}},
    },
}


class PointDiscoveryToGraphBody(BaseModel):
    """Body for POST /bacnet/point_discovery_to_graph. Discovery + merge into graph + optional TTL file."""

    url: str | None = Field(
        default=None,
        examples=[None],
        description="Gateway URL; omit to use server default (or use ?gateway= from GET /bacnet/gateways)",
    )
    instance: PointDiscoveryInstance | None = Field(
        default_factory=lambda: PointDiscoveryInstance(),
        description="Device to discover; change device_instance only",
    )
    update_graph: bool = Field(
        default=True,
        description="Merge BACnet RDF into in-memory graph",
    )
    write_file: bool = Field(
        default=True,
        description="Write config/data_model.ttl; BACnet also at GET /data-model/ttl",
    )


POINT_DISCOVERY_TO_GRAPH_EXAMPLES = {
    "default": {
        "summary": "Change device_instance only; graph + TTL file",
        "value": {
            "url": None,
            "instance": {"device_instance": 3456789},
            "update_graph": True,
            "write_file": True,
        },
    },
    "device_1234": {
        "summary": "Device 1234, graph + config/data_model.ttl",
        "value": {
            "url": None,
            "instance": {"device_instance": 1234},
            "update_graph": True,
            "write_file": True,
        },
    },
    "graph_only": {
        "summary": "In-memory graph only (no file write)",
        "value": {
            "url": None,
            "instance": {"device_instance": 3456789},
            "update_graph": True,
            "write_file": False,
        },
    },
}


def _body_to_dict(body: WhoIsBody | PointDiscoveryBody | PointDiscoveryToGraphBody | dict) -> dict:
    """Normalize body to dict for _bacnet_url and RPC params."""
    if hasattr(body, "model_dump"):
        return body.model_dump(exclude_none=True, by_alias=False)
    return body or {}


def _bacnet_url(body: dict, override_url: str | None = None) -> str:
    """Resolve BACnet gateway URL. override_url (from ?gateway=) wins; else body.url; else effective default.
    Effective default prefers env OFDD_BACNET_SERVER_URL so Docker (host.docker.internal) works from Swagger when url is omitted."""
    if override_url:
        return override_url.strip().rstrip("/")
    url = (body.get("url") or "").strip().rstrip("/")
    server_url = _effective_bacnet_server_url()
    if url and ("localhost" in url or "127.0.0.1" in url) and server_url:
        url = server_url
    elif not url:
        url = server_url
    return url


# Gateway id enum for Swagger dropdown (built when module loads)
GATEWAY_ID_ENUM = _gateway_enum()


@router.get(
    "/gateways",
    summary="List configured BACnet gateways",
    response_description="List of {id, url, description?}. Use id in ?gateway= on whois_range, point_discovery, point_discovery_to_graph.",
)
def bacnet_gateways():
    """
    Return gateways from config: default (OFDD_BACNET_SERVER_URL) plus entries from OFDD_BACNET_GATEWAYS.
    Use the **id** in the query parameter **gateway** on BACnet POST endpoints to target a specific gateway.
    Docker: set OFDD_BACNET_SERVER_URL to sibling container (e.g. http://bacnet:8080) or host (e.g. http://host.docker.internal:8080).
    """
    return _get_gateways_list()


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
    body: Annotated[WhoIsBody, Body(examples=WHOIS_EXAMPLES)],
    gateway: str | None = Query(
        None,
        description="Gateway id from GET /bacnet/gateways (e.g. default). Omit to use body.url or config default.",
        enum=GATEWAY_ID_ENUM,
    ),
):
    """
    Call diy-bacnet-server `client_whois_range` to discover devices in an instance range.
    Use **gateway** dropdown or GET /bacnet/gateways to pick a configured gateway. Omit url in body to use config.
    """
    params = _body_to_dict(body)
    url = _bacnet_url(params, override_url=_resolve_gateway_url(gateway))
    if not url.startswith("http"):
        return {"ok": False, "error": "Invalid URL"}
    req = body.request
    request = req.model_dump() if req else {"start_instance": 1, "end_instance": 3456799}
    result = _post_rpc(url, "client_whois_range", {"request": request})
    return result


@router.post("/point_discovery", summary="BACnet point discovery")
def bacnet_point_discovery(
    body: Annotated[PointDiscoveryBody, Body(examples=POINT_DISCOVERY_EXAMPLES)],
    gateway: str | None = Query(
        None,
        description="Gateway id from GET /bacnet/gateways (e.g. default). Omit to use body.url or config default.",
        enum=GATEWAY_ID_ENUM,
    ),
):
    """
    Call diy-bacnet-server `client_point_discovery` for a device instance.
    Returns object list; use with POST /points (bacnet_device_id, object_identifier, object_name).
    Use **gateway** dropdown or omit to use config default.
    """
    params = _body_to_dict(body)
    url = _bacnet_url(params, override_url=_resolve_gateway_url(gateway))
    if not url.startswith("http"):
        return {"ok": False, "error": "Invalid URL"}
    inst = body.instance
    instance = inst.model_dump() if inst else {"device_instance": 3456789}
    result = _post_rpc(url, "client_point_discovery", {"instance": instance})
    return result


@router.post(
    "/point_discovery_to_graph", summary="BACnet point discovery → in-memory graph"
)
def bacnet_point_discovery_to_graph(
    body: Annotated[
        PointDiscoveryToGraphBody, Body(examples=POINT_DISCOVERY_TO_GRAPH_EXAMPLES)
    ],
    gateway: str | None = Query(
        None,
        description="Gateway id from GET /bacnet/gateways (e.g. default). Omit to use body.url or config default.",
        enum=GATEWAY_ID_ENUM,
    ),
):
    """
    Call point_discovery, then merge BACnet RDF into the in-memory graph (and optionally data_model.ttl).
    BACnet RDF is visible at GET /data-model/ttl. Use **gateway** dropdown or omit to use config default.
    """
    params = _body_to_dict(body)
    url = _bacnet_url(params, override_url=_resolve_gateway_url(gateway))
    if not url.startswith("http"):
        return {"ok": False, "error": "Invalid URL"}
    inst = body.instance
    instance = inst.model_dump() if inst else {"device_instance": 3456789}
    dev_inst = instance.get("device_instance")
    result = _post_rpc(url, "client_point_discovery", {"instance": instance})
    if not result.get("ok") or not result.get("body"):
        return result
    if not body.update_graph:
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
        if body.write_file:
            write_ok, write_err = graph_write_ttl()
            result["write_ok"] = write_ok
            result["write_error"] = write_err
            result["write_path"] = get_ttl_path_resolved()
    except Exception as e:
        result["graph_error"] = str(e)
    return result
