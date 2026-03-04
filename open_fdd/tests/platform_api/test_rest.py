"""REST tests: health, capabilities, auth, error schema."""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"


def test_capabilities_flags():
    r = client.get("/capabilities")
    assert r.status_code == 200
    data = r.json()
    assert "version" in data
    assert data.get("features", {}).get("websocket") is True
    assert data.get("features", {}).get("fault_state") is True
    assert data.get("features", {}).get("jobs") is True
    assert data.get("features", {}).get("bacnet_write") is True


def test_auth_required_when_api_key_set():
    with patch("open_fdd.platform.api.auth.get_platform_settings") as m:
        s = m.return_value
        s.api_key = "secret123"
        r = client.get("/capabilities")
        # Without Bearer we get 401
        assert r.status_code == 401
        data = r.json()
        assert "error" in data
        assert data["error"].get("code") == "UNAUTHORIZED"
    r = client.get("/capabilities", headers={"Authorization": "Bearer secret123"})
    assert r.status_code == 200


def test_error_schema_on_404():
    from unittest.mock import MagicMock, patch
    with patch("open_fdd.platform.api.points.get_conn") as mock_get_conn:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        mock_get_conn.return_value = conn
        r = client.get("/points/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    data = r.json()
    assert "error" in data
    assert data["error"].get("code") == "NOT_FOUND"
    assert "message" in data["error"]


def test_config_returns_platform_config():
    with patch("open_fdd.platform.api.config.get_config_overlay", return_value=None):
        with patch("open_fdd.platform.api.config.get_config_from_graph", return_value={"open_meteo_enabled": False, "open_meteo_interval_hours": 6}):
            r = client.get("/config")
    assert r.status_code == 200
    data = r.json()
    assert "open_meteo_enabled" in data or "open_meteo_interval_hours" in data


def test_points_list_accepts_limit_offset():
    from unittest.mock import MagicMock
    from contextlib import contextmanager
    with patch("open_fdd.platform.api.points.get_conn") as mock_get_conn:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        mock_get_conn.return_value = conn
        r = client.get("/points?limit=10&offset=0")
    assert r.status_code == 200
    assert r.json() == []
