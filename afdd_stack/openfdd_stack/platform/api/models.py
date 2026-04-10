"""Pydantic models for CRUD API."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_modbus_config_common(v: Any) -> Any:
    """Shared validation for PointCreate / PointUpdate ``modbus_config``."""
    if v is None:
        return None
    if not isinstance(v, dict):
        raise ValueError("modbus_config must be a JSON object or null")
    if len(v) == 0:
        raise ValueError(
            "modbus_config cannot be an empty object; use null to clear Modbus configuration."
        )
    from openfdd_stack.platform.modbus_point_config import normalize_modbus_config

    try:
        n = normalize_modbus_config(v)
    except ValueError as e:
        # e.g. multiple registers[] — preserve the specific operator message
        raise ValueError(str(e)) from e
    if n is None:
        raise ValueError(
            "Invalid modbus_config: require non-empty host, integer address (0-65535), "
            "function holding or input; optional port 1-65535, unit_id 0-247, "
            "timeout 0.1-120 s, count 1-125; decode must be raw|uint16|int16|uint32|int32|float32 when set; "
            "float32, int32, and uint32 require count >= 2 (two 16-bit registers); "
            "scale/offset must be numeric when present. "
            "If you pasted the Modbus test-bench JSON, use the flat per-point shape (or a single-element "
            "registers list is accepted); registers[] with multiple entries belongs only in POST /bacnet/modbus_read_registers."
        )
    return n


class SiteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    metadata_: Optional[dict] = Field(None, alias="metadata")


class SiteUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None
    metadata_: Optional[dict] = Field(None, alias="metadata")


class SiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: datetime


class PointCreate(BaseModel):
    site_id: UUID
    external_id: str = Field(..., min_length=1, max_length=256)
    brick_type: Optional[str] = Field(None, max_length=128)
    fdd_input: Optional[str] = Field(None, max_length=64)
    unit: Optional[str] = Field(None, max_length=32)
    description: Optional[str] = None
    equipment_id: Optional[UUID] = None
    bacnet_device_id: Optional[str] = Field(None, max_length=64)
    object_identifier: Optional[str] = Field(None, max_length=128)
    object_name: Optional[str] = Field(None, max_length=256)
    polling: Optional[bool] = Field(
        True,
        description="If true, BACnet / Modbus scraper polls this point when applicable; set false to exclude.",
    )
    modbus_config: Optional[dict[str, Any]] = Field(
        None,
        description=(
            "Modbus TCP read spec for this point (host, port, unit_id, timeout, function, address, count; "
            "optional decode, scale, offset, label). When set, BACnet fields are usually omitted."
        ),
    )

    @field_validator("modbus_config")
    @classmethod
    def _validate_modbus_config_create(cls, v: Any) -> Any:
        return _validate_modbus_config_common(v)


class PointUpdate(BaseModel):
    brick_type: Optional[str] = Field(None, max_length=128)
    fdd_input: Optional[str] = Field(None, max_length=64)
    unit: Optional[str] = Field(None, max_length=32)
    description: Optional[str] = None
    equipment_id: Optional[UUID] = None
    bacnet_device_id: Optional[str] = Field(None, max_length=64)
    object_identifier: Optional[str] = Field(None, max_length=128)
    object_name: Optional[str] = Field(None, max_length=256)
    polling: Optional[bool] = None
    modbus_config: Optional[dict[str, Any]] = None

    @field_validator("modbus_config")
    @classmethod
    def _validate_modbus_config_update(cls, v: Any) -> Any:
        return _validate_modbus_config_common(v)


class PointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    site_id: UUID
    external_id: str
    brick_type: Optional[str] = None
    fdd_input: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    equipment_id: Optional[UUID] = None
    bacnet_device_id: Optional[str] = None
    object_identifier: Optional[str] = None
    object_name: Optional[str] = None
    polling: bool = True
    modbus_config: Optional[dict[str, Any]] = None
    created_at: datetime


class EquipmentCreate(BaseModel):
    site_id: UUID
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    equipment_type: Optional[str] = None
    metadata_: Optional[dict] = Field(None, alias="metadata")
    feeds_equipment_id: Optional[UUID] = Field(
        None, description="Brick: this equipment feeds that one."
    )
    fed_by_equipment_id: Optional[UUID] = Field(
        None, description="Brick: this equipment is fed by that one."
    )


class EquipmentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None
    equipment_type: Optional[str] = None
    metadata_: Optional[dict] = Field(None, alias="metadata")
    feeds_equipment_id: Optional[UUID] = None
    fed_by_equipment_id: Optional[UUID] = None


class EquipmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    site_id: UUID
    name: str
    description: Optional[str] = None
    equipment_type: Optional[str] = None
    metadata: Optional[dict] = None
    feeds_equipment_id: Optional[UUID] = None
    fed_by_equipment_id: Optional[UUID] = None
    created_at: datetime
