"""HTTP JSON API commissioning — GET/POST polling like Modbus/BACnet."""

from __future__ import annotations

import asyncio
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..deps import require_roles
from ..json_api_service import JsonApiServiceError, execute_json_api_request
from ..json_api_env import env_var_configured, json_api_env_path, load_json_api_env
from ..json_api_presets import list_rest_presets, preset_by_id
from ..json_api_store import (
    OPENWEATHER_URL,
    append_reading_and_ingest,
    delete_endpoint,
    driver_tree,
    list_endpoints,
    poll_status,
    refresh_point,
    register_openweather_bundle,
    register_rest_bundle,
    run_poll_cycle,
    set_endpoint_poll,
    upsert_endpoint,
)
from ..poll_intervals import snap_poll_interval

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


class RestSensorSpec(BaseModel):
    json_path: str = Field(default="", description="Dot path into JSON (HA value_json_path)")
    label: str = Field(default="", description="Historian column name")
    units: str = Field(default="")


class JsonApiRegisterBundleBody(BaseModel):
    resource: str = Field(..., description="HTTP(S) URL — HA resource")
    method: MethodLiteral = Field(default="GET")
    sensors: list[RestSensorSpec] = Field(..., min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = Field(default=None)
    auth_type: AuthTypeLiteral = Field(default="none")
    bearer_token: Optional[str] = None
    basic_user: Optional[str] = None
    basic_password: Optional[str] = None
    verify_tls: bool = True
    poll_interval_s: int = Field(default=900, ge=0)
    enabled: bool = True
    poll_once: bool = Field(default=False, description="Run poll cycle after registering")


class JsonApiTestBody(JsonApiRequestBody):
    sensors: list[RestSensorSpec] = Field(default_factory=list, description="Multi-value probe (HA style)")


class JsonApiPresetRegisterBody(BaseModel):
    preset_id: str
    poll_interval_s: int = Field(default=900, ge=0)
    enabled: bool = True
    poll_once: bool = True


class JsonApiOpenWeatherBody(BaseModel):
    poll_interval_s: int = Field(default=1800, ge=0)
    enabled: bool = True
    poll_once: bool = Field(default=True, description="Run one poll cycle after registering")


@router.get("/api/json-api/presets", dependencies=[_READ])
def json_api_presets_catalog() -> dict:
    return list_rest_presets()


@router.post("/api/json-api/presets/{preset_id}/register", dependencies=[_POLL])
def json_api_preset_register(preset_id: str, body: JsonApiPresetRegisterBody) -> dict:
    preset = preset_by_id(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"unknown preset: {preset_id}")
    required = preset.get("requires_env") or []
    if required:
        missing = [v for v in required if not env_var_configured(str(v))]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"missing env vars: {', '.join(missing)} — see workspace/json_api.env.local",
            )
    import json as _json

    try:
        out = register_rest_bundle(
            resource=str(preset.get("resource") or ""),
            method=str(preset.get("method") or "GET"),
            sensors=list(preset.get("sensors") or []),
            headers_json=(
                _json.dumps(preset["headers_json"])
                if isinstance(preset.get("headers_json"), dict)
                else str(preset.get("headers_json") or "")
            ),
            body_json=str(preset.get("body_json") or ""),
            poll_interval_s=snap_poll_interval(body.poll_interval_s) if body.enabled else 0,
            enabled=body.enabled,
        )
        if body.poll_once and body.enabled:
            out["poll"] = run_poll_cycle(force=True)
        out["preset_id"] = preset_id
        return out
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/json-api/register-bundle", dependencies=[_POLL])
def json_api_register_bundle(body: JsonApiRegisterBundleBody) -> dict:
    import json as _json

    try:
        out = register_rest_bundle(
            resource=body.resource,
            method=body.method,
            sensors=[s.model_dump() for s in body.sensors],
            headers_json=_json.dumps(body.headers) if body.headers else "",
            body_json=_json.dumps(body.body) if body.body is not None else "",
            auth_type=body.auth_type,
            bearer_token=body.bearer_token or "",
            basic_user=body.basic_user or "",
            basic_password=body.basic_password or "",
            verify_tls=body.verify_tls,
            poll_interval_s=snap_poll_interval(body.poll_interval_s) if body.enabled else 0,
            enabled=body.enabled,
        )
        if body.poll_once and body.enabled:
            out["poll"] = run_poll_cycle(force=True)
        return out
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/json-api/test", dependencies=[_READ])
async def json_api_test(body: JsonApiTestBody) -> dict:
    """Probe a REST resource without saving — Home Assistant sensor.rest test."""
    try:
        payload = body.model_dump()
        if body.sensors:
            payload["sensors"] = [s.model_dump() for s in body.sensors]
        return await asyncio.to_thread(execute_json_api_request, payload)
    except JsonApiServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/json-api/env/status", dependencies=[_READ])
def json_api_env_status() -> dict:
    load_json_api_env(reload=True)
    path = json_api_env_path()
    return {
        "ok": True,
        "env_file": str(path),
        "env_file_exists": path.is_file(),
        "variables": {
            "OPENWEATHER_API_KEY": env_var_configured("OPENWEATHER_API_KEY"),
            "OPENWEATHER_CITY": env_var_configured("OPENWEATHER_CITY"),
            "OPENWEATHER_UNITS": env_var_configured("OPENWEATHER_UNITS"),
        },
        "openweather_url_template": OPENWEATHER_URL,
    }


@router.post("/api/json-api/presets/openweather", dependencies=[_POLL])
def json_api_preset_openweather(body: JsonApiOpenWeatherBody) -> dict:
    try:
        out = register_openweather_bundle(
            poll_interval_s=body.poll_interval_s,
            enabled=body.enabled,
        )
        if body.poll_once and body.enabled:
            out["poll"] = run_poll_cycle(force=True)
        return out
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.post("/api/json-api/read_and_store", dependencies=[_POLL])
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
