"""Tests for BACnet / preset inference."""

from __future__ import annotations

from portfolio.central.model_infer import infer_bacnet_device_id, infer_object_identifier


def test_bacnet_device_from_point_id():
    assert infer_bacnet_device_id({"id": "12035-analog-input-1"}) == "12035"
    assert infer_bacnet_device_id({"id": "1100-unknown-1"}, equipment={"bacnet_device_instance": 1100}) == "1100"


def test_object_identifier_from_point_id():
    assert "analog" in infer_object_identifier({"id": "12035-analog-input-1"}).lower()
