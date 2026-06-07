"""Modbus TCP decode and execute path (mocked client)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.modbus_service import (  # noqa: E402
    ModbusServiceError,
    _apply_scale_offset,
    _decode_words,
)


@pytest.fixture
def authed_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!")
    monkeypatch.setenv("OFDD_OPERATOR_USER", "operator")
    monkeypatch.setenv("OFDD_OPERATOR_PASSWORD", "changeme")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


def test_decode_uint16():
    assert _decode_words([0x00FF], "uint16") == 255


def test_decode_float32_requires_two_words():
    with pytest.raises(ModbusServiceError):
        _decode_words([1], "float32")


def test_apply_scale_offset():
    assert _apply_scale_offset(100.0, 0.1, None) == pytest.approx(10.0)


class _FakeModbusClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def open(self):
        return True

    def close(self):
        pass

    def read_holding_registers(self, address, count):
        if address == 184:
            return [85]
        if address == 1:
            return [10]
        return False

    def read_input_registers(self, address, count):
        if address == 500 and count == 2:
            return [0x42F6, 0x2A06]
        return False


def test_execute_modbus_read_request_mocked(monkeypatch):
    monkeypatch.setattr("openfdd_bridge.modbus_service.ModbusClient", _FakeModbusClient)
    from openfdd_bridge.modbus_service import execute_modbus_read_request

    payload = {
        "host": "10.0.0.5",
        "port": 502,
        "unit_id": 1,
        "timeout": 3.0,
        "registers": [
            {
                "address": 184,
                "count": 1,
                "function": "holding",
                "decode": "uint16",
                "label": "soc",
            }
        ],
    }
    result = execute_modbus_read_request(payload)
    assert result["ok"] is True
    assert result["readings"][0]["decoded"] == 85


def test_modbus_read_registers_route(authed_client: TestClient):
    import openfdd_bridge.modbus_service as ms

    class _RouteFakeClient:
        def __init__(self, **kwargs):
            pass

        def open(self):
            return True

        def close(self):
            pass

        def read_holding_registers(self, address, count):
            return [10]

    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
    )
    token = login.json()["token"]
    with patch.object(ms, "ModbusClient", _RouteFakeClient):
        r = authed_client.post(
            "/api/modbus/read_registers",
            json={
                "host": "127.0.0.1",
                "registers": [
                    {"address": 1, "count": 1, "function": "holding", "decode": "uint16"}
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert r.json()["readings"][0]["decoded"] == 10


def test_modbus_read_and_store_ingest(authed_client: TestClient):
    import openfdd_bridge.modbus_service as ms

    class _StoreFakeClient:
        def __init__(self, **kwargs):
            pass

        def open(self):
            return True

        def close(self):
            pass

        def read_holding_registers(self, address, count):
            return [42]

    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
    )
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    with patch.object(ms, "ModbusClient", _StoreFakeClient):
        r = authed_client.post(
            "/api/modbus/read_and_store",
            json={
                "host": "192.168.1.10",
                "unit_id": 2,
                "registers": [
                    {
                        "address": 100,
                        "count": 1,
                        "function": "holding",
                        "decode": "uint16",
                        "label": "test_reg",
                    }
                ],
            },
            headers=headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["readings"][0]["decoded"] == 42
    assert body["ingest"]["ok"] is True
    assert body["ingest"]["samples_appended"] == 1
    assert body["ingest"]["feather_source"] == "modbus"

    reg = authed_client.get("/api/modbus/registers", headers=headers)
    assert reg.status_code == 200
    rows = reg.json()["registers"]
    assert len(rows) == 1
    assert rows[0]["last_value"] == "42"
