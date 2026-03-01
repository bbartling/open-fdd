"""Fault state API tests (GET /faults/active, /faults/state, /faults/definitions)."""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def test_faults_active_empty_without_table():
    with patch("open_fdd.platform.api.faults._fault_state_table_exists", return_value=False):
        r = client.get("/faults/active")
    assert r.status_code == 200
    assert r.json() == []


def test_faults_definitions_returns_list():
    r = client.get("/faults/definitions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
