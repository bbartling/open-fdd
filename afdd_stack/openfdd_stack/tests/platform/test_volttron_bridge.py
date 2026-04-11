"""Unit tests for VOLTTRON ↔ Open-FDD bridge (retrofit foundation)."""

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from openfdd_stack.volttron_bridge.catalog import list_points_for_volttron_device
from openfdd_stack.volttron_bridge.flatten import flatten_device_publish
from openfdd_stack.volttron_bridge.materialize import (
    merge_flatten_into_row,
    scrape_dict_to_external_id_row,
)
from openfdd_stack.volttron_bridge.topics import parse_device_subscription_topic


def test_parse_device_topic_all():
    v = parse_device_subscription_topic("devices/BensFakeAHU/all")
    assert v is not None
    assert v.device_name == "BensFakeAHU"
    assert v.suffix == "all"


def test_parse_device_topic_nested_suffix():
    v = parse_device_subscription_topic("/devices/Zone1VAV/point/analogInput_1/")
    assert v is not None
    assert v.device_name == "Zone1VAV"
    assert v.suffix == "point/analogInput_1"


def test_parse_device_topic_rejects_non_device_root():
    assert parse_device_subscription_topic("datalogger/foo") is None
    assert parse_device_subscription_topic("devices/onlytwo") is None
    assert parse_device_subscription_topic("") is None


def test_flatten_present_value_bacnet_style():
    payload = {
        "analogInput:2": {"presentValue": 55.2, "units": "degreesFahrenheit"},
        "analogInput:6": {"presentValue": 72.0},
    }
    flat = dict(flatten_device_publish(payload))
    assert flat["analogInput:2"] == 55.2
    assert flat["analogInput:6"] == 72.0


def test_flatten_nested_dict_without_present_value():
    payload = {"a": {"b": {"c": 3}}}
    flat = dict(flatten_device_publish(payload))
    assert flat["a.b.c"] == 3


def test_flatten_top_level_scalar_ignored_without_prefix():
    payload = {"x": 1}
    flat = dict(flatten_device_publish(payload))
    assert flat["x"] == 1


def test_scrape_to_external_id_suffix():
    flat = {"devices.OA_T": 40.0, "ZoneTemp": 72.5}
    row = scrape_dict_to_external_id_row(flat, ["OA_T", "ZoneTemp"])
    assert row["OA_T"] == 40.0
    assert row["ZoneTemp"] == 72.5


def test_scrape_to_external_id_explicit_map():
    flat = {"path.to.signal": 99}
    row = scrape_dict_to_external_id_row(
        flat,
        ["SAT"],
        path_to_external_id={"path.to.signal": "SAT"},
    )
    assert row["SAT"] == 99


def test_scrape_to_external_id_no_match():
    row = scrape_dict_to_external_id_row({"other": 1}, ["missing"])
    assert row["missing"] is None


def test_merge_flatten_into_row():
    base: dict = {"existing": 0}
    merge_flatten_into_row(base, {"a.b": 2}, ["a.b"])
    assert base["existing"] == 0
    assert base["a.b"] == 2


def test_list_points_for_volttron_device_queries():
    site = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    UUID(site)  # must be valid uuid string

    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.execute.return_value = None
    cursor.fetchall.return_value = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "external_id": "SAT",
            "equipment_name": "AHU1",
        }
    ]

    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor

    with patch(
        "openfdd_stack.volttron_bridge.catalog.get_conn",
        return_value=conn,
    ):
        rows = list_points_for_volttron_device(site, "AHU1")

    assert len(rows) == 1
    assert rows[0]["external_id"] == "SAT"
    cursor.execute.assert_called_once()
    args = cursor.execute.call_args[0]
    assert "equipment" in args[0].lower()
    assert args[1] == (site, "AHU1")


def test_list_points_for_volttron_device_invalid_site():
    with pytest.raises(ValueError, match="site_id must be a UUID"):
        list_points_for_volttron_device("not-a-uuid", "AHU1")
