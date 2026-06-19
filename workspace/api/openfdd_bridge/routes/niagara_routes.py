"""Niagara baskStream connector REST API (read-only)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..deps import require_roles
from ..niagara_service import (
    browse_tree,
    close_persistent_client,
    discover_points,
    list_schedules,
    poll_station_once,
    read_point_ords,
    test_station,
)
from ..niagara_store import (
    delete_station,
    driver_tree,
    get_station,
    health_summary,
    list_stations,
    load_points_cache,
    poll_status,
    set_poll_running,
    upsert_station,
)
from ..niagara_secrets import store_password

router = APIRouter(tags=["niagara"])

_READ = Depends(require_roles("operator", "integrator", "agent"))
_POLL = Depends(require_roles("integrator", "agent"))


def _apply_station_password(payload: dict[str, Any]) -> dict[str, Any]:
    raw_pw = str(payload.pop("password", "") or "").strip()
    env_name = str(payload.get("password_env") or "OPENFDD_NIAGARA_ADMIN_PASSWORD").strip()
    if not env_name:
        payload["password_env"] = "OPENFDD_NIAGARA_ADMIN_PASSWORD"
        env_name = payload["password_env"]
    if raw_pw:
        store_password(station_id=str(payload.get("id") or ""), env_name=env_name, password=raw_pw)
    return payload


class NiagaraStationBody(BaseModel):
    id: str = ""
    name: str = Field(min_length=1)
    station_url: str = Field(min_length=8)
    username: str = Field(min_length=1)
    password_env: str = Field(default="OPENFDD_NIAGARA_ADMIN_PASSWORD")
    password: str = Field(default="", description="Lab-only — stored server-side, never returned")
    verify_tls: bool = False
    enabled: bool = False
    root_ord: str = "slot:/Drivers"
    poll_interval_seconds: int = Field(default=60, ge=15, le=3600)
    read_batch_size: int = Field(default=50, ge=1, le=200)
    browse_depth: int = Field(default=4, ge=1, le=12)
    max_nodes: int = Field(default=2000, ge=50, le=20000)
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    default_points_root: str = ""
    follow_external: bool = False
    include_proxy_ext: bool = False

    @field_validator("station_url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        text = (value or "").strip().rstrip("/")
        if not text.startswith(("http://", "https://")):
            raise ValueError("station_url must start with http:// or https://")
        return text


class NiagaraDiscoverBody(BaseModel):
    base: Optional[str] = None
    depth: Optional[int] = None
    query: str = ""
    follow_external: Optional[bool] = None
    include_proxy_ext: Optional[bool] = None


class NiagaraReadBody(BaseModel):
    ords: list[str] = Field(min_length=1, max_length=500)
    chunk_size: Optional[int] = None
    store: bool = False


class NiagaraScheduleBody(BaseModel):
    base: Optional[str] = None
    depth: int = Field(default=5, ge=1, le=12)
    query: str = ""
    read: bool = False


@router.get("/api/niagara/health", dependencies=[_READ])
def niagara_health() -> dict[str, Any]:
    return health_summary()


@router.get("/api/niagara/stations", dependencies=[_READ])
def niagara_list_stations() -> dict[str, Any]:
    return {"stations": list_stations(), "count": len(list_stations())}


@router.post("/api/niagara/stations", dependencies=[_POLL])
def niagara_create_station(body: NiagaraStationBody) -> dict[str, Any]:
    station = upsert_station(_apply_station_password(body.model_dump()))
    return {"ok": True, "station": station}


@router.put("/api/niagara/stations/{station_id}", dependencies=[_POLL])
def niagara_update_station(station_id: str, body: NiagaraStationBody) -> dict[str, Any]:
    payload = _apply_station_password(body.model_dump())
    payload["id"] = station_id
    station = upsert_station(payload)
    return {"ok": True, "station": station}


@router.delete("/api/niagara/stations/{station_id}", dependencies=[_POLL])
async def niagara_delete_station(station_id: str) -> dict[str, Any]:
    if not delete_station(station_id):
        raise HTTPException(status_code=404, detail="station not found")
    await close_persistent_client(station_id)
    return {"ok": True, "station_id": station_id}


@router.post("/api/niagara/stations/{station_id}/test", dependencies=[_READ])
async def niagara_test_station(station_id: str) -> dict[str, Any]:
    try:
        return await test_station(station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc


@router.post("/api/niagara/stations/{station_id}/discover", dependencies=[_READ])
async def niagara_discover(station_id: str, body: NiagaraDiscoverBody | None = None) -> dict[str, Any]:
    body = body or NiagaraDiscoverBody()
    try:
        return await discover_points(
            station_id,
            base=body.base,
            depth=body.depth,
            query=body.query,
            follow_external=body.follow_external,
            include_proxy_ext=body.include_proxy_ext,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc


@router.get("/api/niagara/stations/{station_id}/tree", dependencies=[_READ])
async def niagara_tree(
    station_id: str,
    base: str = "slot:/Drivers",
    depth: int = 3,
    follow_external: bool | None = None,
) -> dict[str, Any]:
    try:
        return await browse_tree(station_id, base=base, depth=depth, follow_external=follow_external)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc


@router.get("/api/niagara/stations/{station_id}/points", dependencies=[_READ])
def niagara_points(station_id: str) -> dict[str, Any]:
    if get_station(station_id) is None:
        raise HTTPException(status_code=404, detail="station not found")
    points = load_points_cache(station_id)
    return {"station_id": station_id, "count": len(points), "points": points}


@router.post("/api/niagara/stations/{station_id}/read", dependencies=[_READ])
async def niagara_read(station_id: str, body: NiagaraReadBody) -> dict[str, Any]:
    try:
        return await read_point_ords(
            station_id,
            body.ords,
            chunk_size=body.chunk_size,
            store=body.store,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc


@router.get("/api/niagara/stations/{station_id}/schedules", dependencies=[_READ])
async def niagara_schedules(
    station_id: str,
    base: str | None = None,
    depth: int = 5,
    query: str = "",
    read: bool = False,
) -> dict[str, Any]:
    try:
        return await list_schedules(station_id, base=base, depth=depth, query=query, read=read)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc


@router.post("/api/niagara/stations/{station_id}/schedules/read", dependencies=[_READ])
async def niagara_schedules_read(station_id: str, body: NiagaraScheduleBody) -> dict[str, Any]:
    try:
        return await list_schedules(
            station_id,
            base=body.base,
            depth=body.depth,
            query=body.query,
            read=True,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc


@router.post("/api/niagara/stations/{station_id}/poll/start", dependencies=[_POLL])
def niagara_poll_start(station_id: str) -> dict[str, Any]:
    if get_station(station_id) is None:
        raise HTTPException(status_code=404, detail="station not found")
    return set_poll_running(station_id, True)


@router.post("/api/niagara/stations/{station_id}/poll/stop", dependencies=[_POLL])
async def niagara_poll_stop(station_id: str) -> dict[str, Any]:
    if get_station(station_id) is None:
        raise HTTPException(status_code=404, detail="station not found")
    out = set_poll_running(station_id, False)
    await close_persistent_client(station_id)
    return out


@router.get("/api/niagara/stations/{station_id}/poll/status", dependencies=[_READ])
def niagara_poll_status_route(station_id: str) -> dict[str, Any]:
    if get_station(station_id) is None:
        raise HTTPException(status_code=404, detail="station not found")
    return poll_status(station_id)


@router.get("/api/niagara/driver/tree", dependencies=[_READ])
def niagara_driver_tree() -> dict[str, Any]:
    return driver_tree()


@router.post("/api/niagara/stations/{station_id}/poll/once", dependencies=[_POLL])
async def niagara_poll_once(station_id: str) -> dict[str, Any]:
    try:
        return await poll_station_once(station_id, persistent=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc
