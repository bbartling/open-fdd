"""Unit tests for BACnet → BRICK mapping (bacnet_brick module)."""

import pytest

from open_fdd.platform.bacnet_brick import (
    object_identifier_to_brick,
    object_type_to_brick,
)


def test_object_type_to_brick_analog():
    assert object_type_to_brick("analog-input") == "Sensor"
    assert object_type_to_brick("analog-output") == "Sensor"
    assert object_type_to_brick("analog-value") == "Sensor"


def test_object_type_to_brick_binary():
    assert object_type_to_brick("binary-input") == "State"
    assert object_type_to_brick("binary-value") == "State"


def test_object_type_to_brick_with_instance():
    assert object_type_to_brick("analog-input,3") == "Sensor"
    assert object_type_to_brick("binary-value,1") == "State"


def test_object_type_to_brick_case_insensitive():
    assert object_type_to_brick("ANALOG-INPUT") == "Sensor"
    assert object_type_to_brick("Temperature-Sensor") == "Sensor"


def test_object_type_to_brick_unknown_returns_none():
    assert object_type_to_brick("unknown-type") is None
    assert object_type_to_brick("") is None
    assert object_type_to_brick(None) is None


def test_object_identifier_to_brick():
    assert object_identifier_to_brick("analog-input,5") == "Sensor"
    assert object_identifier_to_brick("temperature-sensor,1") == "Sensor"
    assert object_identifier_to_brick(None) is None
