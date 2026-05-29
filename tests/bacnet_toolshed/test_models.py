"""Pydantic BACnet model validation — no live BACnet I/O."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bacnet_toolshed.models import (
    DeviceInstanceRequest,
    DiscoverRequest,
    ReadMultiplePropertiesRequest,
    ReadMultiplePropertiesRequestWrapper,
    ReadPriorityArrayRequest,
    SingleReadRequest,
    WritePropertyRequest,
    parse_object_identifier_parts,
)


def test_discover_request_defaults():
    req = DiscoverRequest()
    assert req.range_low == 1
    assert req.range_high == 4194303


def test_parse_object_identifier_parts_valid():
    obj_type, inst = parse_object_identifier_parts("analog-value,42")
    assert obj_type == "analog-value"
    assert inst == 42


def test_parse_object_identifier_parts_invalid():
    with pytest.raises(ValueError):
        parse_object_identifier_parts("bad")
    with pytest.raises(ValueError):
        parse_object_identifier_parts("invalid-type,1")


def test_single_read_request_valid():
    req = SingleReadRequest(
        device_instance=123,
        object_identifier="analog-input,1",
        property_identifier="present-value",
    )
    assert req.property_identifier == "present-value"


def test_write_property_request_null_release():
    req = WritePropertyRequest(
        device_instance=1,
        object_identifier="analog-output,1",
        property_identifier="present-value",
        value=None,
        priority=8,
    )
    assert req.value is None
    assert req.priority == 8


def test_write_property_request_invalid_property():
    with pytest.raises(ValidationError):
        WritePropertyRequest(
            device_instance=1,
            object_identifier="analog-output,1",
            property_identifier="not-a-property",
            value=1.0,
        )


def test_read_multiple_wrapper():
    req = ReadMultiplePropertiesRequestWrapper(
        device_instance=100,
        requests=[
            ReadMultiplePropertiesRequest(
                object_identifier="analog-input,1",
                property_identifier="present-value",
            )
        ],
    )
    assert len(req.requests) == 1


def test_read_priority_array_request():
    req = ReadPriorityArrayRequest(
        device_instance=50,
        object_identifier="analog-output,2",
    )
    assert req.object_identifier == "analog-output,2"


def test_device_instance_request_bounds():
    with pytest.raises(ValidationError):
        DeviceInstanceRequest(device_instance=99999999)
