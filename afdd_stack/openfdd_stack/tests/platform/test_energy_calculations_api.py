"""Tests for /energy-calculations (mock DB)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from openfdd_stack.platform.api.main import app

client = TestClient(app)


def _energy_conn(fetchone=None, fetchall=None, fetchone_side_effect=None):
    cursor = MagicMock()
    cursor.execute.return_value = None
    cursor.rowcount = 1
    if fetchone_side_effect is not None:
        cursor.fetchone.side_effect = fetchone_side_effect
    else:
        cursor.fetchone.return_value = fetchone
    if fetchall is not None:
        cursor.fetchall.return_value = fetchall
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    return conn


@patch("openfdd_stack.platform.api.energy_calculations.sync_ttl_to_file")
@patch("openfdd_stack.platform.api.energy_calculations.emit")
def test_calc_types(mock_emit, mock_sync):
    r = client.get("/energy-calculations/calc-types")
    assert r.status_code == 200
    data = r.json()
    assert "calc_types" in data
    ids = {c["id"] for c in data["calc_types"]}
    assert "runtime_electric_kw" in ids
    mock_emit.assert_not_called()


def test_preview_runtime_electric():
    r = client.post(
        "/energy-calculations/preview",
        json={
            "calc_type": "runtime_electric_kw",
            "parameters": {"kw": 10, "hours_fault": 100, "electric_rate_per_kwh": 0.1},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["annual_kwh_saved"] == 1000.0
    assert body["annual_cost_saved_usd"] == 100.0


def test_preview_unknown_type_400():
    r = client.post(
        "/energy-calculations/preview",
        json={"calc_type": "not_a_real_calc", "parameters": {}},
    )
    assert r.status_code == 400


def test_list_by_site_empty():
    site_id = uuid4()
    conn = _energy_conn(fetchall=[])
    with patch(
        "openfdd_stack.platform.api.energy_calculations.get_conn",
        side_effect=lambda: conn,
    ):
        r = client.get(f"/energy-calculations?site_id={site_id}")
    assert r.status_code == 200
    assert r.json() == []


@patch("openfdd_stack.platform.api.energy_calculations.sync_ttl_to_file")
@patch("openfdd_stack.platform.api.energy_calculations.emit")
def test_create_energy_calc(mock_emit, mock_sync):
    site_id = uuid4()
    ec_id = uuid4()
    now = datetime.now(timezone.utc)
    row = {
        "id": ec_id,
        "site_id": site_id,
        "equipment_id": None,
        "external_id": "rt_kw_1",
        "name": "Fan runtime",
        "description": None,
        "calc_type": "runtime_electric_kw",
        "parameters": {"kw": 5},
        "point_bindings": {},
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    conn = _energy_conn(fetchone_side_effect=[None, row])
    with patch(
        "openfdd_stack.platform.api.energy_calculations.get_conn",
        side_effect=lambda: conn,
    ):
        r = client.post(
            "/energy-calculations",
            json={
                "site_id": str(site_id),
                "external_id": "rt_kw_1",
                "name": "Fan runtime",
                "calc_type": "runtime_electric_kw",
                "parameters": {"kw": 5},
                "point_bindings": {},
                "enabled": True,
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["external_id"] == "rt_kw_1"
    assert data["calc_type"] == "runtime_electric_kw"
    mock_sync.assert_called_once()
    mock_emit.assert_called_once()


@patch("openfdd_stack.platform.api.energy_calculations.sync_ttl_to_file")
@patch("openfdd_stack.platform.api.energy_calculations.emit")
def test_create_energy_calc_duplicate_409(mock_emit, mock_sync):
    site_id = uuid4()
    ec_id = uuid4()
    now = datetime.now(timezone.utc)
    existing = {
        "id": ec_id,
        "site_id": site_id,
        "equipment_id": None,
        "external_id": "dup",
        "name": "Existing",
        "description": None,
        "calc_type": "runtime_electric_kw",
        "parameters": {},
        "point_bindings": {},
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    conn = _energy_conn(fetchone=existing)
    with patch(
        "openfdd_stack.platform.api.energy_calculations.get_conn",
        side_effect=lambda: conn,
    ):
        r = client.post(
            "/energy-calculations",
            json={
                "site_id": str(site_id),
                "external_id": "dup",
                "name": "New name",
                "calc_type": "runtime_electric_kw",
                "parameters": {"kw": 1},
                "point_bindings": {},
                "enabled": True,
            },
        )
    assert r.status_code == 409
    mock_emit.assert_not_called()


@patch("openfdd_stack.platform.api.energy_calculations.sync_ttl_to_file")
@patch("openfdd_stack.platform.api.energy_calculations.emit")
def test_export_energy_bundle(mock_emit, mock_sync):
    site_id = uuid4()
    ec_id = uuid4()
    now = datetime.now(timezone.utc)
    calc_row = {
        "id": ec_id,
        "site_id": site_id,
        "equipment_id": None,
        "external_id": "fan_rt",
        "name": "Fan runtime",
        "description": None,
        "calc_type": "runtime_electric_kw",
        "parameters": {"kw": 2},
        "point_bindings": {},
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    conn = _energy_conn()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = {"id": site_id, "name": "Building A"}
    cur.fetchall.side_effect = [[calc_row], []]
    with patch(
        "openfdd_stack.platform.api.energy_calculations.get_conn",
        side_effect=lambda: conn,
    ):
        r = client.get(f"/energy-calculations/export?site_id={site_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["format"] == "openfdd_energy_calculations_v1"
    assert data["site_name"] == "Building A"
    assert len(data["calc_types"]) >= 1
    assert len(data["energy_calculations"]) == 1
    assert data["energy_calculations"][0]["external_id"] == "fan_rt"
    assert len(data.get("penalty_catalog") or []) == 18
    mock_emit.assert_not_called()


def test_penalty_catalog_get():
    r = client.get("/energy-calculations/penalty-catalog")
    assert r.status_code == 200
    data = r.json()
    assert len(data["penalty_catalog"]) == 18
    assert data["penalty_catalog"][0]["seq"] == 1


@patch("openfdd_stack.platform.api.energy_calculations.sync_ttl_to_file")
@patch("openfdd_stack.platform.api.energy_calculations.emit")
def test_seed_default_penalty_catalog(mock_emit, mock_sync):
    site_id = uuid4()
    conn = _energy_conn()
    cur = conn.cursor.return_value.__enter__.return_value
    # 1× site check, then 18× “no existing row” for penalty_default_01 … _18
    cur.fetchone.side_effect = [{"id": site_id}] + [None] * 18
    with patch(
        "openfdd_stack.platform.api.energy_calculations.get_conn",
        side_effect=lambda: conn,
    ):
        r = client.post(f"/energy-calculations/seed-default-penalty-catalog?site_id={site_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 18
    assert body["rows_in_catalog"] == 18
    mock_sync.assert_called_once()


@patch("openfdd_stack.platform.api.energy_calculations.sync_ttl_to_file")
@patch("openfdd_stack.platform.api.energy_calculations.emit")
def test_import_creates_calc(mock_emit, mock_sync):
    site_id = uuid4()
    new_id = uuid4()
    conn = _energy_conn()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [
        {"id": site_id},
        None,
        {"id": new_id},
    ]
    with patch(
        "openfdd_stack.platform.api.energy_calculations.get_conn",
        side_effect=lambda: conn,
    ):
        r = client.put(
            "/energy-calculations/import",
            json={
                "site_id": str(site_id),
                "energy_calculations": [
                    {
                        "external_id": "imported_1",
                        "name": "Imported",
                        "calc_type": "runtime_electric_kw",
                        "parameters": {"kw": 1, "hours_fault": 10, "electric_rate_per_kwh": 0.1},
                        "point_bindings": {},
                        "enabled": True,
                    }
                ],
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1
    assert body["updated"] == 0
    assert body["total"] == 1
    mock_sync.assert_called_once()
    mock_emit.assert_called()


def test_export_site_missing_404():
    site_id = uuid4()
    conn = _energy_conn()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = None
    with patch(
        "openfdd_stack.platform.api.energy_calculations.get_conn",
        side_effect=lambda: conn,
    ):
        r = client.get(f"/energy-calculations/export?site_id={site_id}")
    assert r.status_code == 404
