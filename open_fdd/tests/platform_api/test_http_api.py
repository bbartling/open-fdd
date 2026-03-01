# HTTP/API tests mirroring node-red-contrib-home-assistant-websocket homeAssistant/http.test.ts

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def test_capabilities_requires_bearer_when_api_key_set():
    with patch("open_fdd.platform.api.auth.get_platform_settings") as m:
        m.return_value.api_key = "secret123"
        r = client.get("/capabilities")
        assert r.status_code == 401
        assert r.json().get("error", {}).get("code") == "UNAUTHORIZED"
        r = client.get("/capabilities", headers={"Authorization": "Bearer secret123"})
        assert r.status_code == 200


def test_faults_active_requires_bearer_when_api_key_set():
    with patch("open_fdd.platform.api.auth.get_platform_settings") as m:
        m.return_value.api_key = "token456"
        r = client.get("/faults/active")
        assert r.status_code == 401
        r = client.get("/faults/active", headers={"Authorization": "Bearer token456"})
        assert r.status_code == 200


def test_jobs_fdd_run_requires_bearer_when_api_key_set():
    with patch("open_fdd.platform.api.auth.get_platform_settings") as m:
        m.return_value.api_key = "key789"
        r = client.post("/jobs/fdd/run", json={})
        assert r.status_code == 401
        r = client.post("/jobs/fdd/run", json={}, headers={"Authorization": "Bearer key789"})
        assert r.status_code == 200
        assert "job_id" in r.json()


def test_403_for_invalid_api_key():
    with patch("open_fdd.platform.api.auth.get_platform_settings") as m:
        m.return_value.api_key = "correct_key"
        r = client.get("/capabilities", headers={"Authorization": "Bearer wrong_key"})
        assert r.status_code == 403
        assert r.json().get("error", {}).get("code") == "FORBIDDEN"


def test_capabilities_returns_version_and_features():
    r = client.get("/capabilities")
    assert r.status_code == 200
    data = r.json()
    assert "version" in data and "features" in data
    assert data["features"].get("websocket") is True
    assert data["features"].get("fault_state") is True


def test_faults_active_returns_list():
    assert client.get("/faults/active").status_code == 200
    assert isinstance(client.get("/faults/active").json(), list)


def test_faults_active_accepts_query_params():
    r = client.get("/faults/active?site_id=default&equipment_id=ahu1")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_entities_suggested_returns_list():
    with patch("open_fdd.platform.api.entities.get_conn") as mock_conn:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = conn
        r = client.get("/entities/suggested")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_401_has_error_code_and_message():
    with patch("open_fdd.platform.api.auth.get_platform_settings") as m:
        m.return_value.api_key = "x"
        r = client.get("/capabilities")
        assert r.status_code == 401
        err = r.json().get("error")
        assert err and "code" in err and "message" in err


def test_404_has_error_code_not_found():
    with patch("open_fdd.platform.api.points.get_conn") as mock_conn:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = conn
        r = client.get("/points/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    assert r.json().get("error", {}).get("code") == "NOT_FOUND"


def test_422_validation_has_error_details():
    r = client.post("/points", json={})
    assert r.status_code == 422
    data = r.json()
    assert data.get("error", {}).get("code") == "VALIDATION_ERROR"
    assert data.get("error", {}).get("details") is not None
