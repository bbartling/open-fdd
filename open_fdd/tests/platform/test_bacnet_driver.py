"""Tests for BACnet driver (data-model scrape path, get_bacnet_points_from_data_model)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from open_fdd.platform.drivers.bacnet import (
    get_bacnet_points_from_data_model,
)


def test_get_bacnet_points_from_data_model_empty():
    """When no points have BACnet addressing, returns empty list."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

    with patch("open_fdd.platform.drivers.bacnet.get_conn", side_effect=lambda: conn):
        out = get_bacnet_points_from_data_model()
    assert out == []


def test_get_bacnet_points_from_data_model_returns_normalized_rows():
    """Returns list of dicts with site_id, external_id, bacnet_device_id, object_identifier, object_name, device_id."""
    site_id = uuid4()
    rows = [
        {
            "id": uuid4(),
            "site_id": site_id,
            "external_id": "DAP-P",
            "bacnet_device_id": "3456789",
            "object_identifier": "analog-input,1",
            "object_name": "DAP-P",
        },
        {
            "id": uuid4(),
            "site_id": site_id,
            "external_id": "BV-1",
            "bacnet_device_id": "device,999",
            "object_identifier": "binary-value,1",
            "object_name": "BV-1",
        },
    ]
    conn = MagicMock()
    cursor = MagicMock()
    cursor.execute.return_value = None
    cursor.fetchall.return_value = rows
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

    with patch("open_fdd.platform.drivers.bacnet.get_conn", side_effect=lambda: conn):
        out = get_bacnet_points_from_data_model(site_id=None)
    assert len(out) == 2
    assert out[0]["site_id"] == str(site_id)
    assert out[0]["external_id"] == "DAP-P"
    assert out[0]["bacnet_device_id"] == "3456789"
    assert out[0]["object_identifier"] == "analog-input,1"
    assert out[0]["object_name"] == "DAP-P"
    assert out[0]["device_id"] == "device,3456789"
    assert out[1]["device_id"] == "device,999"


def test_get_bacnet_points_from_data_model_filters_by_site_id():
    """When site_id is passed, executes query with site filter."""
    site_id = "default"
    conn = MagicMock()
    cursor = MagicMock()
    cursor.execute.return_value = None
    cursor.fetchall.return_value = []
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

    with patch("open_fdd.platform.drivers.bacnet.get_conn", side_effect=lambda: conn):
        get_bacnet_points_from_data_model(site_id=site_id)
    cursor.execute.assert_called_once()
    args = cursor.execute.call_args[0]
    assert "s.id::text = %s OR s.name = %s" in args[0] or "JOIN sites" in args[0]
    assert args[1] == (site_id, site_id)
