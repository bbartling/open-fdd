"""Fault state API tests (GET /faults/active, /faults/state, /faults/definitions, /faults/bacnet-devices)."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)

_SITE_FILTER_SQL_FRAGMENT = (
    "fs.site_id = %s OR fs.site_id IN (SELECT name FROM sites WHERE id::text = %s)"
)


def _make_conn_with_execute_capture() -> tuple[MagicMock, list[tuple[str, tuple | list | None]]]:
    """Context-manager conn + cursor that record every cursor.execute(query, params)."""
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
    return conn, execute_calls


def _assert_site_filter_execute(
    execute_calls: list[tuple[str, tuple | list | None]], site_key: str
) -> None:
    assert any(
        _SITE_FILTER_SQL_FRAGMENT in q and params == (site_key, site_key)
        for q, params in execute_calls
    ), f"expected site filter SQL + params in execute_calls, got: {execute_calls!r}"


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
    conn, execute_calls = _make_conn_with_execute_capture()

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
    _assert_site_filter_execute(execute_calls, site_key)


def test_faults_state_site_filter_matches_uuid_or_stored_name():
    """GET /faults/state?site_id= uses same dual-key site filter as /faults/active."""
    site_key = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    conn, execute_calls = _make_conn_with_execute_capture()

    with (
        patch(
            "open_fdd.platform.api.faults._fault_state_table_exists", return_value=True
        ),
        patch("open_fdd.platform.api.faults.get_conn", side_effect=lambda: conn),
    ):
        r = client.get(f"/faults/state?site_id={site_key}")

    assert r.status_code == 200
    assert r.json() == []
    assert len(execute_calls) >= 1
    _assert_site_filter_execute(execute_calls, site_key)
