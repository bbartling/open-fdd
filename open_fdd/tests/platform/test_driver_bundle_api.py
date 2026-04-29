from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from open_fdd.gateway.server import create_app


def test_drivers_export_shape() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/config/drivers/export")
        assert r.status_code == 200
        body = r.json()
        assert body.get("schema_version") == 1
        assert "weather" in body and "onboard" in body and "bacnet" in body and "health" in body


def test_drivers_validate_ok_minimal() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.post(
            "/config/drivers/validate",
            json={
                "weather": {
                    "latitude": 40.0,
                    "longitude": -74.0,
                    "timezone": "UTC",
                    "base_url": "https://archive-api.open-meteo.com/v1/archive",
                }
            },
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True
        assert r.json().get("errors") == {}


def test_drivers_validate_typo_warning() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.post(
            "/config/drivers/validate",
            json={
                "bacnet": {
                    "enabled": False,
                    "interval_seconds": 300,
                    "site_id": "x",
                    "server_url": "http://127.0.1:8765/client_read_multiple",
                    "api_key": None,
                }
            },
        )
        assert r.status_code == 200
        j = r.json()
        assert j.get("ok") is True
        assert any("127.0.1" in w for w in j.get("warnings", []))


def test_drivers_validate_bad_weather() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.post(
            "/config/drivers/validate",
            json={"weather": {"latitude": "nope"}},
        )
        assert r.status_code == 200
        j = r.json()
        assert j.get("ok") is False
        assert "weather" in j.get("errors", {})
