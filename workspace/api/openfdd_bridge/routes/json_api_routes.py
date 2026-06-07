"""HTTP JSON API commissioning — GET/POST polling like Modbus/BACnet."""

from __future__ import annotations

import asyncio
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..deps import require_roles
from ..json_api_service import JsonApiServiceError, execute_json_api_request
from ..json_api_store import (
    append_reading_and_ingest,
    delete_endpoint,
    driver_tree,
    list_endpoints,
    poll_status,
    refresh_point,
    run_poll_cycle,
    set_endpoint_poll,
    upsert_endpoint,
)

router = APIRouter(tags=["json_api"])

_READ = Depends(require_roles("operator", "integrator", "agent"))
_POLL = Depends(require_roles("integrator", "agent"))

MethodLiteral = Literal["GET", "POST"]
AuthTypeLiteral = Literal["none", "bearer", "basic"]


class JsonApiRequestBody(BaseModel):
    url: str = Field(..., description="Full HTTP(S) URL")
    method: MethodLiteral = Field(default="GET")
    json_path: str = Field(default="", description="Dot path into JSON body, e.g. title or address.city")
    label: Optional[str] = Field(default=None, description="Historian column name")
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = Field(default=None, description="JSON body for POST")
    auth_type: AuthTypeLiteral = Field(default="none", description="Outbound auth: none, bearer, or basic")
    bearer_token: Optional[str] = Field(default=None, description="Bearer/API token when auth_type=bearer")
    basic_user: Optional[str] = Field(default=None, description="HTTP Basic username")
    basic_password: Optional[str] = Field(default=None, description="HTTP Basic password")
    verify_tls: bool = Field(default=True, description="Verify TLS certificates (disable for self-signed OT gateways)")
    timeout: float = Field(default=5.0, ge=0.5, le=60.0)

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("url must be non-empty")
        return text


class JsonApiReadStoreBody(JsonApiRequestBody):
    site_id: Optional[str] = None
    save_endpoint: bool = Field(default=True)


class JsonApiEndpointUpsertBody(BaseModel):
    point_id: Optional[str] = None
    url: str
    method: MethodLiteral = Field(default="GET")
    json_path: str = Field(default="")
    headers_json: str = Field(default="")
    body_json: str = Field(default="")
    auth_type: AuthTypeLiteral = Field(default="none")
    bearer_token: Optional[str] = Field(default=None)
    basic_user: Optional[str] = Field(default=None)
    basic_password: Optional[str] = Field(default=None)
    verify_tls: bool = Field(default=True)
    label: Optional[str] = None
    units: Optional[str] = None
    enabled: bool = False
    poll_interval_s: int = Field(default=0, ge=0)


class JsonApiEndpointPollBody(BaseModel):
    point_id: str
    enabled: bool
    poll_interval_s: int = Field(default=0, ge=0)


class JsonApiRefreshBody(BaseModel):
    point_id: str
    store: bool = False


@router.get("/api/json-api/driver/tree", dependencies=[_READ])
def json_api_driver_tree() -> dict:
    return driver_tree()


@router.get("/api/json-api/poll/status", dependencies=[_READ])
def json_api_poll_status_route() -> dict:
    return poll_status()


@router.post("/api/json-api/poll/once", dependencies=[_POLL])
async def json_api_poll_once() -> dict:
    return await asyncio.to_thread(run_poll_cycle, force=True)


@router.post("/api/json-api/refresh", dependencies=[_READ])
async def json_api_refresh(body: JsonApiRefreshBody) -> dict:
    try:
        return await asyncio.to_thread(refresh_point, body.point_id, store=body.store)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/api/json-api/endpoint/{point_id}", dependencies=[_POLL])
def json_api_delete_endpoint(point_id: str) -> dict:
    try:
        return delete_endpoint(point_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/json-api/endpoints", dependencies=[_READ])
def json_api_endpoints_list() -> dict:
    return list_endpoints()


@router.post("/api/json-api/endpoints", dependencies=[_POLL])
def json_api_endpoints_upsert(body: JsonApiEndpointUpsertBody) -> dict:
    try:
        return upsert_endpoint(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/json-api/endpoint/poll", dependencies=[_POLL])
def json_api_endpoint_poll(body: JsonApiEndpointPollBody) -> dict:
    try:
        return set_endpoint_poll(
            point_id=body.point_id,
            enabled=body.enabled,
            poll_interval_s=body.poll_interval_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/json-api/request", dependencies=[_READ])
async def json_api_request(body: JsonApiRequestBody) -> dict:
    try:
        payload = body.model_dump()
        return await asyncio.to_thread(execute_json_api_request, payload)
    except JsonApiServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/json-api/read_and_store", dependencies=[_READ])
async def json_api_read_and_store(body: JsonApiReadStoreBody) -> dict:
    try:
        payload = body.model_dump(exclude={"site_id", "save_endpoint"})
        reading = await asyncio.to_thread(execute_json_api_request, payload)
        if body.save_endpoint and reading.get("success"):
            import json as _json

            upsert_endpoint(
                {
                    "url": body.url,
                    "method": body.method,
                    "json_path": body.json_path,
                    "label": reading.get("label") or body.label or body.json_path or "value",
                    "headers_json": _json.dumps(body.headers) if body.headers else "",
                    "body_json": _json.dumps(body.body) if body.body is not None else "",
                    "auth_type": body.auth_type,
                    "bearer_token": body.bearer_token or "",
                    "basic_user": body.basic_user or "",
                    "basic_password": body.basic_password or "",
                    "verify_tls": "1" if body.verify_tls else "0",
                    "units": "",
                    "last_value": str(reading.get("present_value") or ""),
                }
            )
        ingest = None
        if reading.get("success"):
            ingest = append_reading_and_ingest(reading=reading, site_id=body.site_id)
        return {**reading, "ingest": ingest}
    except JsonApiServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
