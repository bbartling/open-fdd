"""Fault state API tests (GET /faults/active, /faults/state, /faults/definitions, /faults/bacnet-devices)."""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def test_faults_bacnet_devices_returns_list():
    """GET /faults/bacnet-devices returns list from data model (points + equipment)."""
    with patch("open_fdd.platform.api.faults.get_conn") as mock_conn:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = conn
        r = client.get("/faults/bacnet-devices")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    if data:
        assert "bacnet_device_id" in data[0] and "equipment_name" in data[0]


def test_faults_active_empty_without_table():
    with patch(
        "open_fdd.platform.api.faults._fault_state_table_exists", return_value=False
    ):
        r = client.get("/faults/active")
    assert r.status_code == 200
    assert r.json() == []


def test_faults_definitions_returns_list():
    r = client.get("/faults/definitions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_faults_active_site_filter_matches_uuid_or_stored_name():
    """
    Regression: /faults/active?site_id=<uuid> must match fault_state rows keyed by site
    display name (legacy) or UUID, same as /download/faults and analytics.
    """
    site_key = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    execute_calls: list[tuple[str, tuple | list | None]] = []

    def capture_execute(query, params=None):
        execute_calls.append((query, params))

    cursor = MagicMock()
    cursor.execute = MagicMock(side_effect=capture_execute)
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

    with (
        patch(
            "open_fdd.platform.api.faults._fault_state_table_exists", return_value=True
        ),
        patch("open_fdd.platform.api.faults.get_conn", side_effect=lambda: conn),
    ):
        r = client.get(f"/faults/active?site_id={site_key}")

    assert r.status_code == 200
    assert r.json() == []
    assert len(execute_calls) >= 1
    select_q, select_params = execute_calls[-1]
    assert (
        "fs.site_id = %s OR fs.site_id IN (SELECT name FROM sites WHERE id::text = %s)"
        in select_q
    )
    assert select_params == (site_key, site_key)
