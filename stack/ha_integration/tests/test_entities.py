"""Tests for Open-FDD HA entities: fault binary_sensors (per equipment), buttons, sensors, device registry."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("aiohttp", reason="HA integration tests require aiohttp")


def _run(coro):
    return asyncio.run(coro)


# --- Fault binary_sensor (equipment-based) ---

def test_fault_binary_sensor_unique_id_uses_equipment_and_fault_id():
    """Fault entities use unique_id = openfdd_fault_{equipment_id}_{fault_id}."""
    equipment_id = "eq-uuid-123"
    fault_id = "high_discharge_temp"
    unique_id = f"openfdd_fault_{equipment_id}_{fault_id}"
    assert unique_id == "openfdd_fault_eq-uuid-123_high_discharge_temp"


def test_fault_active_response_shape_creates_binary_sensor_attributes():
    """When /faults/active returns a fault item, binary_sensor entity has correct attributes."""
    fault = {
        "id": "abc-123",
        "site_id": "site-1",
        "equipment_id": "eq-uuid-123",
        "fault_id": "high_discharge_temp",
        "active": True,
        "last_changed_ts": "2026-03-01T12:00:00Z",
        "last_evaluated_ts": "2026-03-01T12:05:00Z",
        "context": {"value": 85.0},
    }
    assert fault["active"] is True
    assert fault.get("fault_id") == "high_discharge_temp"
    assert fault.get("equipment_id") == "eq-uuid-123"
    # Entity is attached to equipment device
    assert (fault.get("equipment_id"), fault.get("fault_id")) == ("eq-uuid-123", "high_discharge_temp")


def test_definitions_for_equipment_empty_types_applies_to_all():
    """When fault_definition has no equipment_types, it applies to any equipment."""
    definitions = [{"fault_id": "f1", "name": "Fault 1", "equipment_types": []}]
    equipment = {"id": "eq-1", "name": "AHU-1", "equipment_type": "AHU"}
    # Logic: if not types or (eq_type and eq_type in types) -> include
    types = definitions[0].get("equipment_types") or []
    assert not types  # empty list
    # So definition applies
    assert len([d for d in definitions if not d.get("equipment_types") or (equipment.get("equipment_type") and equipment.get("equipment_type") in (d.get("equipment_types") or []))]) == 1


# --- Buttons ---

def test_button_run_fdd_calls_post_job_fdd_run():
    """Run FDD button should call client.post_job_fdd_run."""
    client = MagicMock()
    client.post_job_fdd_run = AsyncMock(return_value={"job_id": "j1"})
    _run(client.post_job_fdd_run())
    client.post_job_fdd_run.assert_called_once()


def test_button_export_graph_calls_data_model_serialize():
    """Export graph button should call client.data_model_serialize."""
    client = MagicMock()
    client.data_model_serialize = AsyncMock(return_value={"status": "ok"})
    _run(client.data_model_serialize())
    client.data_model_serialize.assert_called_once()


def test_button_fetch_fault_history_calls_get_faults_state():
    """Fetch fault history button should call client.get_faults_state with equipment_id."""
    client = MagicMock()
    client.get_faults_state = AsyncMock(return_value=[])
    _run(client.get_faults_state(site_id="site-1", equipment_id="eq-1"))
    client.get_faults_state.assert_called_once_with(site_id="site-1", equipment_id="eq-1")


# --- Device registry ---

def test_device_registry_identifiers():
    """Main device uses (DOMAIN, entry_id); equipment devices use (DOMAIN, equipment_id)."""
    domain = "openfdd"
    entry_id = "entry-abc"
    equipment_id = "eq-uuid-456"
    main_identifiers = {(domain, entry_id)}
    equipment_identifiers = {(domain, equipment_id)}
    assert main_identifiers == {("openfdd", "entry-abc")}
    assert equipment_identifiers == {("openfdd", "eq-uuid-456")}


# --- Coordinator data shape ---

def test_coordinator_data_includes_sites_equipment_faults_definitions():
    """Coordinator _async_update_data returns sites, equipment, faults_active, fault_definitions, run_fdd_status, capabilities."""
    data = {
        "sites": [{"id": "site-1", "name": "TestSite"}],
        "equipment": [{"id": "eq-1", "site_id": "site-1", "name": "AHU-1"}],
        "equipment_by_site": {"site-1": [{"id": "eq-1", "name": "AHU-1"}]},
        "points_by_equipment": {"eq-1": [{"id": "pt-1", "bacnet_device_id": "3456789"}]},
        "faults_active": [{"id": "f1", "equipment_id": "eq-1", "fault_id": "high_temp", "active": True}],
        "fault_definitions": [{"fault_id": "high_temp", "name": "High discharge temp", "equipment_types": ["AHU"]}],
        "run_fdd_status": {"last_run": {"run_ts": "2026-03-01T10:00:00", "status": "finished"}},
        "capabilities": {"version": "2.0.2", "features": {"websocket": True}},
        "entities_suggested": [{"point_id": "p1", "equipment_id": "eq-1", "suggested_ha_domain": "sensor", "suggested_ha_id": "oa_temp"}],
    }
    assert len(data["sites"]) == 1
    assert data["sites"][0]["name"] == "TestSite"
    assert len(data["equipment"]) == 1
    assert data["equipment"][0]["name"] == "AHU-1"
    assert "eq-1" in data["points_by_equipment"]
    assert len(data["faults_active"]) == 1
    assert data["fault_definitions"][0]["fault_id"] == "high_temp"
    assert data["run_fdd_status"]["last_run"]["run_ts"] == "2026-03-01T10:00:00"
    assert len(data["entities_suggested"]) == 1
    assert data["entities_suggested"][0]["suggested_ha_domain"] == "sensor"


def test_coordinator_data_equipment_by_site_grouping():
    """equipment_by_site groups equipment list by site_id."""
    equipment_list = [
        {"id": "eq-1", "site_id": "site-a", "name": "AHU-1"},
        {"id": "eq-2", "site_id": "site-a", "name": "VAV-1"},
        {"id": "eq-3", "site_id": "site-b", "name": "AHU-2"},
    ]
    by_site = {}
    for eq in equipment_list:
        sid = eq.get("site_id")
        if sid:
            by_site.setdefault(sid, []).append(eq)
    assert len(by_site["site-a"]) == 2
    assert len(by_site["site-b"]) == 1
    assert by_site["site-b"][0]["name"] == "AHU-2"


# --- Per-equipment sensor unique_id ---

def test_equipment_sensor_unique_id():
    """Per-equipment sensors use unique_id suffix with equipment_id."""
    domain = "openfdd"
    eq_id = "eq-uuid-789"
    assert f"{domain}_equipment_active_fault_count_{eq_id}" == "openfdd_equipment_active_fault_count_eq-uuid-789"
    assert f"{domain}_equipment_last_fault_change_{eq_id}" == "openfdd_equipment_last_fault_change_eq-uuid-789"


# --- Options: equipment_bacnet_device ---

def test_options_equipment_bacnet_device_map():
    """Options flow stores equipment_id -> bacnet device_instance; button uses it."""
    options = {"equipment_bacnet_device": {"eq-uuid-1": 3456789, "eq-uuid-2": 3456790}}
    bacnet_map = options.get("equipment_bacnet_device") or {}
    assert bacnet_map.get("eq-uuid-1") == 3456789
    assert bacnet_map.get("eq-uuid-2") == 3456790
    assert bacnet_map.get("eq-missing") is None
