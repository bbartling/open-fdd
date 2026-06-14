"""Driver point contract normalization tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.driver_point_contract import (  # noqa: E402
    canonical_source,
    normalize_bacnet_point,
    normalize_bacnet_value,
    normalize_json_api_point,
    normalize_modbus_point,
    normalize_niagara_point,
    normalize_niagara_value,
    values_compatible,
)


def test_canonical_source_aliases():
    assert canonical_source("bacnet") == "bacnet_direct"
    assert canonical_source("niagara_baskstream") == "niagara_baskstream"


def test_niagara_point_preserves_ord_encoding():
    row = {
        "station_id": "bench9065",
        "point_ord": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/OA$2dT",
        "point_name": "OA-T",
        "type_spec": "control:NumericPoint",
    }
    out = normalize_niagara_point(row)
    assert "$20" in out["point_path"]
    assert "$2d" in out["point_path"]
    assert out["source"] == "niagara_baskstream"


def test_bacnet_point_preserves_object_identifier():
    row = {
        "point_id": "5007-analog-input-1173",
        "device_instance": "5007",
        "object_name": "OA-T",
        "object_identifier": "analog-input,1173",
        "object_type": "analog-input",
        "fdd_input": "oa-t",
    }
    out = normalize_bacnet_point(row)
    assert out["point_path"] == "analog-input,1173"
    assert out["source"] == "bacnet_direct"


def test_cross_source_numeric_compatible():
    b = normalize_bacnet_value(point_id="5007-analog-input-1173", value=76.2, semantic_point_id="oa-t")
    n = normalize_niagara_value({"point_ord": "slot:/x/OA$2dT", "value": 76.5}, semantic_point_id="oa-t")
    cmp = values_compatible(b, n, kind="numeric", tolerance=1.0)
    assert cmp["pass"] is True
    assert cmp["abs_diff"] == pytest.approx(0.3)


def test_cross_source_boolean_exact():
    b = normalize_bacnet_value(point_id="p1", value=False, semantic_point_id="current-s")
    n = normalize_niagara_value({"point_ord": "slot:/x/CURRENT$2dS", "value": False}, semantic_point_id="current-s")
    cmp = values_compatible(b, n, kind="boolean")
    assert cmp["pass"] is True


def test_niagara_display_value_fallback():
    row = normalize_niagara_value({"point_ord": "slot:/x", "value": 72.5, "status": "{ok}"})
    assert row["display_value"] == 72.5


def test_modbus_and_json_api_contract_fields():
    mod = normalize_modbus_point({"point_id": "m1", "host": "127.0.0.1", "port": 502, "label": "temp", "address": 100})
    js = normalize_json_api_point({"point_id": "j1", "host": "api.example.com", "label": "oat", "url": "https://x"})
    for out in (mod, js):
        assert "source" in out
        assert "raw_point_id" in out
        assert "point_path" in out
