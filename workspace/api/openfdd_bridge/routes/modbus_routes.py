"""Modbus TCP client reads — orthogonal to BACnet commissioning."""

from __future__ import annotations

import asyncio
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..deps import require_roles
from ..modbus_service import ModbusServiceError, execute_modbus_read_request

router = APIRouter(tags=["modbus"])

_READ = Depends(require_roles("operator", "integrator", "agent"))

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


@router.post("/api/modbus/read_registers", dependencies=[_READ])
async def modbus_read_registers(body: ModbusReadRequestBody) -> dict:
    try:
        payload = body.model_dump()
        return await asyncio.to_thread(execute_modbus_read_request, payload)
    except ModbusServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"modbus_tcp_error: {exc}") from exc
