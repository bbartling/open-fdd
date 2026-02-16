"""Pydantic models for CRUD API."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class PointUpdate(BaseModel):
    brick_type: Optional[str] = Field(None, max_length=128)
    fdd_input: Optional[str] = Field(None, max_length=64)
    unit: Optional[str] = Field(None, max_length=32)
    description: Optional[str] = None
    equipment_id: Optional[UUID] = None
    bacnet_device_id: Optional[str] = Field(None, max_length=64)
    object_identifier: Optional[str] = Field(None, max_length=128)
    object_name: Optional[str] = Field(None, max_length=256)


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
    created_at: datetime


class EquipmentCreate(BaseModel):
    site_id: UUID
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    equipment_type: Optional[str] = None
    metadata_: Optional[dict] = Field(None, alias="metadata")


class EquipmentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None
    equipment_type: Optional[str] = None
    metadata_: Optional[dict] = Field(None, alias="metadata")


class EquipmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    site_id: UUID
    name: str
    description: Optional[str] = None
    equipment_type: Optional[str] = None
    created_at: datetime
