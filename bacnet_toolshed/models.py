"""Pydantic request models for BACnet client/server HTTP APIs (diy-bacnet-server aligned)."""

from __future__ import annotations

from typing import List, Optional, Union

from bacpypes3.primitivedata import ObjectType, PropertyIdentifier
from pydantic import BaseModel, ConfigDict, Field, field_validator


def parse_object_identifier_parts(value: str) -> tuple[str, int]:
    """Parse ``objectType,instanceNumber`` and return ``(object_type, instance)``."""
    if "," not in value:
        raise ValueError("Must be in the format objectType,instanceNumber")
    object_type, instance_str = value.split(",", 1)
    object_type = object_type.strip()
    if object_type not in ObjectType._enum_map:
        raise ValueError(f"Invalid object type: {object_type}")
    try:
        instance = int(instance_str.strip())
    except ValueError as exc:
        raise ValueError("Instance number must be an integer") from exc
    if not (0 <= instance <= 4194303):
        raise ValueError("Instance out of range")
    return object_type, instance


class DiscoverRequest(BaseModel):
    range_low: int = Field(default=1, ge=0, le=4194303)
    range_high: int = Field(default=4194303, ge=0, le=4194303)


class DeviceInstanceRequest(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    device_address: str = ""


class WritePropertyRequest(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    object_identifier: str
    property_identifier: str = "present-value"
    value: Union[float, int, str, None] = None
    priority: Optional[int] = Field(default=None, ge=1, le=16)

    @field_validator("property_identifier")
    @classmethod
    def validate_property_identifier(cls, value: str) -> str:
        if value not in PropertyIdentifier._enum_map:
            raise ValueError(f"Invalid property_identifier: {value}")
        return value

    @field_validator("object_identifier")
    @classmethod
    def validate_object_identifier(cls, value: str) -> str:
        parse_object_identifier_parts(value)
        return value


class ReadMultiplePropertiesRequest(BaseModel):
    object_identifier: str
    property_identifier: str

    @field_validator("object_identifier")
    @classmethod
    def validate_object_identifier(cls, value: str) -> str:
        parse_object_identifier_parts(value)
        return value

    @field_validator("property_identifier")
    @classmethod
    def validate_property_identifier(cls, value: str) -> str:
        if value not in PropertyIdentifier._enum_map:
            raise ValueError(f"Invalid property identifier: {value}")
        return value


class ReadMultiplePropertiesRequestWrapper(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    requests: List[ReadMultiplePropertiesRequest]


class SingleReadRequest(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    object_identifier: str
    property_identifier: str = "present-value"

    @field_validator("object_identifier")
    @classmethod
    def validate_object_identifier(cls, value: str) -> str:
        parse_object_identifier_parts(value)
        return value

    @field_validator("property_identifier")
    @classmethod
    def validate_property_identifier(cls, value: str) -> str:
        if value not in PropertyIdentifier._enum_map:
            raise ValueError(f"Invalid property identifier: {value}")
        return value


class ReadPriorityArrayRequest(BaseModel):
    device_instance: int = Field(ge=0, le=4194303)
    object_identifier: str

    @field_validator("object_identifier")
    @classmethod
    def validate_object_identifier(cls, value: str) -> str:
        parse_object_identifier_parts(value)
        return value


class PriorityArraySlot(BaseModel):
    priority_level: int
    type: str
    value: Union[str, float, int, bool, None] = None


class ServerPointSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    object_identifier: str
    present_value: Union[str, float, int, bool, None] = None
    commandable: bool = False
