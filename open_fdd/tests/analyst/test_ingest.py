"""Tests for analyst ingest."""

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from open_fdd.analyst.ingest import (
    _parse_path,
    _normalize_equipment_id,
    process_inner_zip,
)
from open_fdd.analyst.config import AnalystConfig


def test_parse_path():
    """Parse BACnet-style path string."""
    p = _parse_path("Site / Building / Floor / Area / B203_Heat Pump 33 / DAT")
    assert p["site"] == "Site"
    assert p["equipment"] == "B203_Heat Pump 33"
    assert p["point"] == "DAT"


def test_normalize_equipment_id():
    """Normalize equipment name to ID."""
    assert _normalize_equipment_id("B203_Heat Pump 33") == "hp_B203_33"
    # "Heat Pump 1" -> prefix empty -> "hp" fallback -> hp_hp_1
    assert _normalize_equipment_id("Heat Pump 1") == "hp_hp_1"


@pytest.fixture
def sample_inner_zip(tmp_path):
    """Create a minimal inner zip with path headers."""
    zip_path = tmp_path / "device.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        # CSV with path header
        csv_content = '"Site / Building / Floor / Area / B203_Heat Pump 33 / DAT"\n2024-01-15,72.5'
        z.writestr("point1.csv", csv_content)
        csv_content2 = '"Site / Building / Floor / Area / B203_Heat Pump 33 / Zone Temp"\n2024-01-15,68.0'
        z.writestr("point2.csv", csv_content2)
        csv_content3 = '"Site / Building / Floor / Area / B203_Heat Pump 33 / Fan Status"\n2024-01-15,1'
        z.writestr("point3.csv", csv_content3)
    return zip_path


def test_process_inner_zip(sample_inner_zip):
    """Process inner zip extracts equipment and point mappings."""
    rows = process_inner_zip(sample_inner_zip, sample_inner_zip.parent)
    assert len(rows) >= 2
    eq_ids = {r["equipment_id"] for r in rows}
    assert "hp_B203_33" in eq_ids
    point_types = {r["point_type"] for r in rows}
    assert (
        "dat" in point_types
        or "zone_temp" in point_types
        or "fan_status" in point_types
    )
