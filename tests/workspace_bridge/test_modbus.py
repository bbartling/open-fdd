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


def test_fake_modbus_server_read_and_ingest(monkeypatch, tmp_path):
    """Integration: scripts/fake_modbus_temp_server.py + driver ingest + feather."""
    import subprocess
    import time

    port = 15502
    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO / "scripts" / "fake_modbus_temp_server.py"),
            "--port",
            str(port),
            "--flatline",
            "70.0",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.5)
        monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "data"))
        for name in list(sys.modules):
            if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
                del sys.modules[name]
        from openfdd_bridge.modbus_service import execute_modbus_read_request
        from openfdd_bridge.modbus_store import append_samples_and_ingest
        from openfdd_bridge.data_loader import load_site_frame

        payload = {
            "host": "127.0.0.1",
            "port": port,
            "unit_id": 1,
            "timeout": 2.0,
            "registers": [
                {
                    "address": 100,
                    "count": 1,
                    "function": "holding",
                    "decode": "uint16",
                    "scale": 0.1,
                    "label": "fake-temp",
                }
            ],
        }
        for _ in range(3):
            result = execute_modbus_read_request(payload)
            assert result["readings"][0]["success"] is True
            assert result["readings"][0]["decoded"] == pytest.approx(70.0)
            ingest = append_samples_and_ingest(
                host="127.0.0.1",
                unit_id=1,
                readings=result["readings"],
                site_id="modbus-test",
            )
            assert ingest["ok"] is True
            time.sleep(1.05)

        df = load_site_frame("modbus-test", source="modbus", columns=["fake-temp"])
        assert df is not None
        assert len(df) >= 1
        assert "fake-temp" in df.columns
    finally:
        proc.terminate()
        proc.wait(timeout=3)


def test_modbus_driver_tree_and_poll_status(monkeypatch, tmp_path):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "data"))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.modbus_store import driver_tree, poll_status, upsert_register

    upsert_register(
        {
            "host": "127.0.0.1",
            "port": 5502,
            "unit_id": 1,
            "address": 100,
            "function": "holding",
            "decode": "uint16",
            "scale": 0.1,
            "label": "fake-temp",
            "units": "degF",
            "enabled": True,
            "poll_interval_s": 60,
            "last_value": "72.5",
        }
    )
    tree = driver_tree()
    assert tree["ok"] is True
    assert len(tree["devices"]) == 1
    assert tree["devices"][0]["poll_count"] == 1
    assert tree["devices"][0]["points"][0]["present_value"] == "72.5"
    status = poll_status()
    assert status["enabled_points"] == 1
