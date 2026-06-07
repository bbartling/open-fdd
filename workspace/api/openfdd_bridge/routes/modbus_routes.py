"""Modbus TCP client reads — orthogonal to BACnet commissioning."""

from __future__ import annotations

import asyncio
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..deps import require_roles
from ..modbus_service import ModbusServiceError, execute_modbus_read_request
from ..modbus_store import (
    append_samples_and_ingest,
    delete_register,
    driver_tree,
    list_registers,
    poll_status,
    refresh_point,
    run_poll_cycle,
    set_register_poll,
    upsert_register,
)

router = APIRouter(tags=["modbus"])

_READ = Depends(require_roles("operator", "integrator", "agent"))
_POLL = Depends(require_roles("integrator", "agent"))

DecodeLiteral = Literal["raw", "uint16", "int16", "uint32", "int32", "float32"]
FunctionLiteral = Literal["holding", "input"]


class ModbusRegisterOp(BaseModel):
    address: int = Field(..., ge=0, le=65535)
    count: int = Field(default=1, ge=1, le=125)
    function: FunctionLiteral = Field(default="holding")
    decode: Optional[DecodeLiteral] = Field(default=None)
    scale: Optional[float] = Field(default=None)
    offset: Optional[float] = Field(default=None)
    label: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def decode_needs_word_count(self) -> ModbusRegisterOp:
        if self.decode in ("float32", "uint32", "int32") and self.count < 2:
            raise ValueError(
                f"decode={self.decode!r} requires count >= 2 (two 16-bit Modbus words)"
            )
        return self


class ModbusReadRequestBody(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "host": "10.200.200.170",
                "port": 502,
                "unit_id": 1,
                "timeout": 5.0,
                "registers": [
                    {
                        "address": 184,
                        "count": 1,
                        "function": "holding",
                        "decode": "uint16",
                        "label": "Battery SoC %",
                    }
                ],
            }
        }
    )

    host: str = Field(..., description="Modbus TCP host (IP or DNS).")
    port: int = Field(default=502, ge=1, le=65535)
    unit_id: int = Field(default=1, ge=0, le=255)
    timeout: float = Field(default=5.0, ge=0.5, le=60.0)
    registers: list[ModbusRegisterOp] = Field(..., min_length=1, max_length=32)

    @field_validator("host")
    @classmethod
    def strip_host(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("host must be non-empty")
        return text


class ModbusReadStoreBody(ModbusReadRequestBody):
    site_id: Optional[str] = Field(default=None, description="Site id for feather shard (default site).")
    save_registers: bool = Field(
        default=True,
        description="Upsert each successful reading into modbus/commissioning/registers.csv.",
    )


class ModbusRegisterUpsertBody(BaseModel):
    point_id: Optional[str] = None
    host: str
    port: int = Field(default=502, ge=1, le=65535)
    unit_id: int = Field(default=1, ge=0, le=255)
    address: int = Field(..., ge=0, le=65535)
    function: FunctionLiteral = Field(default="holding")
    count: int = Field(default=1, ge=1, le=125)
    decode: Optional[DecodeLiteral] = Field(default="uint16")
    scale: Optional[float] = None
    offset: Optional[float] = None
    label: Optional[str] = None
    units: Optional[str] = None
    enabled: bool = False
    poll_interval_s: int = Field(default=0, ge=0)


class ModbusRegisterPollBody(BaseModel):
    point_id: str
    enabled: bool
    poll_interval_s: int = Field(default=0, ge=0)


class ModbusRefreshBody(BaseModel):
    point_id: str
    store: bool = Field(default=False, description="Also append sample to historian")


@router.get("/api/modbus/driver/tree", dependencies=[_READ])
def modbus_driver_tree() -> dict:
    return driver_tree()


@router.get("/api/modbus/poll/status", dependencies=[_READ])
def modbus_poll_status_route() -> dict:
    return poll_status()


@router.post("/api/modbus/poll/once", dependencies=[_POLL])
async def modbus_poll_once() -> dict:
    return await asyncio.to_thread(run_poll_cycle, force=True)


@router.post("/api/modbus/refresh", dependencies=[_READ])
async def modbus_refresh_register(body: ModbusRefreshBody) -> dict:
    try:
        return await asyncio.to_thread(refresh_point, body.point_id, store=body.store)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/api/modbus/register/{point_id}", dependencies=[_POLL])
def modbus_delete_register(point_id: str) -> dict:
    try:
        return delete_register(point_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/modbus/registers", dependencies=[_READ])
def modbus_registers_list() -> dict:
    return list_registers()


@router.post("/api/modbus/registers", dependencies=[_POLL])
def modbus_registers_upsert(body: ModbusRegisterUpsertBody) -> dict:
    try:
        return upsert_register(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/modbus/register/poll", dependencies=[_POLL])
def modbus_register_poll(body: ModbusRegisterPollBody) -> dict:
    try:
        return set_register_poll(
            point_id=body.point_id,
            enabled=body.enabled,
            poll_interval_s=body.poll_interval_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/modbus/read_registers", dependencies=[_READ])
async def modbus_read_registers(body: ModbusReadRequestBody) -> dict:
    try:
        payload = body.model_dump()
        return await asyncio.to_thread(execute_modbus_read_request, payload)
    except ModbusServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"modbus_tcp_error: {exc}") from exc


@router.post("/api/modbus/read_and_store", dependencies=[_READ])
async def modbus_read_and_store(body: ModbusReadStoreBody) -> dict:
    """Read Modbus TCP registers, append poll CSV, and write feather shard (source=modbus)."""
    try:
        payload = body.model_dump(exclude={"site_id", "save_registers"})
        result = await asyncio.to_thread(execute_modbus_read_request, payload)
        if body.save_registers:
            for spec, reading in zip(body.registers, result.get("readings") or [], strict=True):
                if not reading.get("success"):
                    continue
                upsert_register(
                    {
                        "host": body.host,
                        "port": body.port,
                        "unit_id": body.unit_id,
                        "address": spec.address,
                        "function": spec.function,
                        "count": spec.count,
                        "decode": spec.decode or "uint16",
                        "scale": spec.scale,
                        "offset": spec.offset,
                        "label": reading.get("label") or spec.label,
                        "units": "degF",
                        "last_value": str(reading.get("decoded") or ""),
                    }
                )
        ingest = append_samples_and_ingest(
            host=body.host,
            unit_id=body.unit_id,
            readings=result.get("readings") or [],
            site_id=body.site_id,
        )
        return {**result, "ingest": ingest}
    except ModbusServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"modbus_tcp_error: {exc}") from exc
