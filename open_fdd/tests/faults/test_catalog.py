"""Grade-A fault catalog validation."""

from __future__ import annotations

from open_fdd.faults import get_fault, legacy_alias, list_faults, load_catalog


def test_catalog_loads_and_validates():
    catalog = load_catalog()
    assert len(catalog) >= 19


def test_legacy_alias_maps_ahu_e():
    assert legacy_alias("AHU-E") == "AHU-ECON-001"


def test_get_fault_by_code():
    fault = get_fault("DATA-STAL-001")
    assert fault is not None
    assert fault.canonical_id == "data.telemetry.stale_point"
    assert fault.category == "data_quality"


def test_all_faults_have_required_metadata():
    for fault in list_faults():
        errors = fault.validate()
        assert not errors, f"{fault.code}: {errors}"
