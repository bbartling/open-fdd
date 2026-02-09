"""Tests for analyst brick model generation."""

from pathlib import Path

import pandas as pd
import pytest

from open_fdd.analyst.brick_model import build_brick_ttl


def test_build_brick_ttl(tmp_path):
    """Build Brick TTL from equipment catalog."""
    catalog = tmp_path / "equipment.csv"
    catalog.write_text(
        "equipment_id,equipment_label,point_type,inner_zip\n"
        "hp_1,Heat Pump 1,dat,x.zip\n"
        "hp_1,Heat Pump 1,zone_temp,x.zip\n"
        "hp_1,Heat Pump 1,fan_status,x.zip\n"
    )
    ttl = build_brick_ttl(catalog, site_name="Test Site")
    assert "brick:Heat_Pump" in ttl
    assert "Test Site" in ttl
    assert "hp_1" in ttl
    assert "ofdd:mapsToRuleInput" in ttl
    assert "sat" in ttl
    assert "zt" in ttl
    assert "fan_status" in ttl
